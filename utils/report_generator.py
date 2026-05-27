import pandas as pd

# ── re-use the fast vectorised builders from validators ───────────────────────
from utils.validators import (
    _safe_num, _safe_str, _normalise_status,
    _build_article_map, _build_ecom_map, _build_tc_map,
    _build_stock_map, _build_excl_map, _build_launch_map,
    _apply_exclusion, _needs_buffer,
)




def _sku_logic_for_report(ecom_status, tc_stock, max_0, article_no, excl_map):
    """
    Derive Final Status for the Status Report tab.
    Mirrors the logic in validators._sku_logic but returns only Final Status.
    """
    excl = _apply_exclusion(article_no, tc_stock, excl_map, max_0)
    if excl:
        return excl[0]   # final_status
    if ecom_status == "Inactive":
        return "Inactive"
    if tc_stock == 0:
        return "Inactive"
    return "Active"


def generate_status_report(data, country):
    all_df    = data.get("all_file",  pd.DataFrame())
    tc_inv    = data.get("tc_inv",    pd.DataFrame())
    content   = data.get("content",   pd.DataFrame())
    zecom     = data.get("zecom",     pd.DataFrame())
    exclusion = data.get("exclusion", pd.DataFrame())

    # Build all lookup maps once (vectorised — fast)
    article_map  = _build_article_map(content)
    excl_map     = _build_excl_map(exclusion)
    tc_map       = _build_tc_map(tc_inv)
    launch_map   = _build_launch_map(zecom)

    mp_sources = {}

    lazada = data.get("lazada", pd.DataFrame())
    if lazada is not None and not lazada.empty and "SKU" in lazada.columns:
        mp_sources["Lazada " + country] = lazada

    shopee = data.get("shopee", pd.DataFrame())
    if shopee is not None and not shopee.empty and "SKU" in shopee.columns:
        mp_sources["Shopee " + country] = shopee

    zalora = data.get("zalora", pd.DataFrame())
    if zalora is not None and not zalora.empty and "SKU" in zalora.columns:
        mp_sources["Zalora " + country] = zalora

    if country == "MY":
        tiktok = data.get("tiktok", pd.DataFrame())
        if tiktok is not None and not tiktok.empty and "SKU" in tiktok.columns:
            mp_sources["TikTok MY"] = tiktok

    if not mp_sources:
        return pd.DataFrame()

    frames = []
    for mp_name, df in mp_sources.items():
        apply_buffer = _needs_buffer(mp_name)
        # Build ecom_map and stock_map per marketplace (buffer differs)
        ecom_map  = _build_ecom_map(zecom, mp_name)
        stock_map = _build_stock_map(all_df, apply_buffer)

        for _, row in df.iterrows():
            sku        = _safe_str(row.get("SKU", ""))
            if not sku:
                continue
            mp_status  = _safe_str(row.get("MP Status", "Unknown"))
            mp_stock   = _safe_num(row.get("MP Stock", 0))
            article_no = article_map.get(sku, "")
            ecom_st    = ecom_map.get(article_no, "Inactive") if article_no else "Inactive"
            launch_dt  = launch_map.get(article_no, "") if article_no else ""
            tc_data    = tc_map.get(sku, {"TC Status": "Unknown", "Max 0": "No"})
            sd         = stock_map.get(sku, {"TC Stock": 0.0, "Reserved Stock": 0.0})
            excl_lbl   = excl_map.get(article_no, "") if article_no else ""
            tc_stock   = sd["TC Stock"]
            max_0      = tc_data["Max 0"]

            final_status = _sku_logic_for_report(
                ecom_st, tc_stock, max_0, article_no, excl_map
            )

            frames.append({
                "Marketplace":    mp_name,
                "Seller SKU":     sku,
                "Article No":     article_no,
                "MP Status":      mp_status,
                "TC Status":      _normalise_status(tc_data["TC Status"]),
                "Final Status":   final_status,
                "e-com (Yes/No)": "Yes" if ecom_st == "Active" else "No",
                "ECOM Status":    ecom_st,
                "Launch Date":    launch_dt,
                "Exclusion":      excl_lbl,
                "MP Stock":       mp_stock,
                "TC Stock":       tc_stock,
                "Reserved Stock": sd["Reserved Stock"],
                "Max 0":          max_0,
            })

    return pd.DataFrame(frames) if frames else pd.DataFrame()
