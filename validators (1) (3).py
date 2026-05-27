import pandas as pd


def _safe_num(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _safe_str(val):
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()


def _normalise_status(status):
    s = _safe_str(status).lower()
    if s in ("active", "1", "enabled", "yes", "y", "live", "listed"):
        return "Active"
    if s in ("inactive", "0", "disabled", "no", "n", "delisted",
             "unlisted", "deleted", "removed"):
        return "Inactive"
    return _safe_str(status)


# ── Vectorised lookup builders (FAST — no iterrows) ───────────────────────────

def _build_article_map(content):
    """Returns dict SKU -> Article No"""
    if content is None or content.empty or "SKU" not in content.columns:
        return {}
    art_col = next(
        (c for c in ["Article No", "Color_No", "Color_No.1", "ArticleNo"]
         if c in content.columns),
        next((c for c in content.columns
              if "article" in c.lower() or "color" in c.lower()), None)
    )
    if not art_col:
        return {}
    sub = content[["SKU", art_col]].copy()
    sub["SKU"] = sub["SKU"].astype(str).str.strip()
    sub[art_col] = sub[art_col].astype(str).str.strip()
    sub = sub[sub["SKU"] != ""].drop_duplicates("SKU")
    return dict(zip(sub["SKU"], sub[art_col]))


def _build_ecom_map(zecom, mp_name):
    """Returns dict Article No -> 'Active'/'Inactive'"""
    if zecom is None or zecom.empty or "Article No" not in zecom.columns:
        return {}
    mp_key = mp_name.split()[0].lower()
    ecom_col = next(
        (c for c in zecom.columns
         if c.startswith("Ecom_") and mp_key in c.lower()), None
    )
    if not ecom_col:
        return {}
    sub = zecom[["Article No", ecom_col]].copy()
    sub["Article No"] = sub["Article No"].astype(str).str.strip()
    sub[ecom_col] = sub[ecom_col].astype(str).str.strip()
    sub = sub[sub["Article No"] != ""].drop_duplicates("Article No")
    return dict(zip(sub["Article No"], sub[ecom_col]))


def _build_tc_map(tc_inv):
    """Returns dict SKU -> {TC Status, Max 0}"""
    if tc_inv is None or tc_inv.empty or "SKU" not in tc_inv.columns:
        return {}
    has_max0 = "Max 0" in tc_inv.columns
    cols = ["SKU", "TC Status"] + (["Max 0"] if has_max0 else [])
    sub = tc_inv[cols].copy()
    sub["SKU"] = sub["SKU"].astype(str).str.strip()
    sub["TC Status"] = sub["TC Status"].astype(str).str.strip().replace("", "Unknown").fillna("Unknown")
    if has_max0:
        sub["Max 0"] = sub["Max 0"].astype(str).str.strip().replace("", "No").fillna("No")
    else:
        sub["Max 0"] = "No"
    sub = sub[sub["SKU"] != ""].drop_duplicates("SKU")
    result = {}
    for sku, tc_status, max_0 in zip(sub["SKU"], sub["TC Status"], sub["Max 0"]):
        result[sku] = {"TC Status": tc_status, "Max 0": max_0}
    return result


def _build_stock_map(all_df, apply_buffer=False):
    """Returns dict SKU -> {TC Stock, Reserved Stock}"""
    if all_df is None or all_df.empty or "SKU" not in all_df.columns:
        return {}
    cols = ["SKU"] + [c for c in ["TC Stock", "Reserved Stock"] if c in all_df.columns]
    sub = all_df[cols].copy()
    sub["SKU"] = sub["SKU"].astype(str).str.strip()
    sub = sub[sub["SKU"] != ""].drop_duplicates("SKU")
    if "TC Stock" not in sub.columns:
        sub["TC Stock"] = 0.0
    if "Reserved Stock" not in sub.columns:
        sub["Reserved Stock"] = 0.0
    sub["TC Stock"] = pd.to_numeric(sub["TC Stock"], errors="coerce").fillna(0)
    sub["Reserved Stock"] = pd.to_numeric(sub["Reserved Stock"], errors="coerce").fillna(0)
    if apply_buffer:
        sub["TC Stock"] = (sub["TC Stock"] - 1).clip(lower=0)
    result = {}
    for sku, tc, res in zip(sub["SKU"], sub["TC Stock"], sub["Reserved Stock"]):
        result[sku] = {"TC Stock": tc, "Reserved Stock": res}
    return result


def _build_excl_map(exclusion):
    """Returns dict Article No -> Exclusion Status"""
    if exclusion is None or exclusion.empty or "Article No" not in exclusion.columns:
        return {}
    sub = exclusion[["Article No", "Exclusion Status"]].copy()
    sub["Article No"] = sub["Article No"].astype(str).str.strip()
    sub = sub[sub["Article No"] != ""].drop_duplicates("Article No")
    return dict(zip(sub["Article No"], sub["Exclusion Status"].astype(str).str.strip()))


def _build_launch_map(zecom):
    """Returns dict Article No -> launch date string (empty string if none)."""
    if zecom is None or zecom.empty or "Article No" not in zecom.columns:
        return {}
    if "Launch Date" not in zecom.columns:
        return {}
    sub = zecom[["Article No", "Launch Date"]].copy()
    sub["Article No"] = sub["Article No"].astype(str).str.strip()
    sub = sub[sub["Article No"] != ""].drop_duplicates("Article No")
    sub["Launch Date"] = pd.to_datetime(sub["Launch Date"], errors="coerce")

    def _fmt(ld):
        if pd.notna(ld):
            try:
                return str(ld.date())
            except Exception:
                return str(ld)
        return ""

    sub["_ld_str"] = sub["Launch Date"].apply(_fmt)
    return dict(zip(sub["Article No"], sub["_ld_str"]))


# ── Business logic helpers ────────────────────────────────────────────────────

def _apply_exclusion(article_no, tc_stock, excl_map, max_0):
    if not article_no or article_no not in excl_map:
        return None
    excl_status = excl_map[article_no]
    if excl_status == "Inactive":
        return ("Inactive", "Inactive as per AM Request", "Set max 0")
    if excl_status == "Active":
        if tc_stock >= 1:
            ma = "Remove max" if max_0 == "Yes" else ""
            return ("Active", "Active as per AM Request", ma)
        else:
            ma = "Remove max" if max_0 == "Yes" else ""
            return ("Inactive", "AM Request Active but 0 Stock", ma)
    return None


def _needs_buffer(mp_name, country=None):
    return mp_name in ("Lazada PH", "TikTok MY")


# ── SKU-level logic (Lazada + Zalora) ────────────────────────────────────────

def _sku_logic(mp_status, mp_stock, ecom_status, tc_status,
               tc_stock, reserved, max_0, article_no, excl_map):

    excl = _apply_exclusion(article_no, tc_stock, excl_map, max_0)
    if excl:
        final_status, comment, max_action = excl
    else:
        if ecom_status == "Inactive":
            final_status = "Inactive"
            comment = "Due to Ecom No"
        elif tc_stock == 0:
            final_status = "Inactive"
            comment = "Due to 0 Stock"
        else:
            final_status = "Active"
            comment = "Ecom Yes with Stock"

        max_action = ""
        if comment == "Due to Ecom No" and max_0 == "No":
            max_action = "Set max 0"
        elif comment in ("Due to 0 Stock", "Ecom Yes with Stock") and max_0 == "Yes":
            max_action = "Remove max"

    mp_norm  = _normalise_status(mp_status)
    tc_norm  = _normalise_status(tc_status)
    fin_norm = final_status

    final_check = (mp_norm == tc_norm == fin_norm)
    stock_check = (mp_stock == tc_stock)

    if not final_check:
        remarks = "Change to Active" if final_status == "Active" else "Change to Inactive"
    elif not stock_check:
        if final_status == "Active":
            if reserved != 0:
                remarks = "Due to Reserved Stock"
            else:
                remarks = "Make Impact"
        else:
            remarks = "Stock not pushed due to Inactive Status"
    else:
        remarks = "All Good"

    push_0 = "Yes" if (tc_stock <= 0 and mp_stock > 0) else ""

    return {
        "Final Status":  final_status,
        "Comments":      comment,
        "Final Check":   str(final_check),
        "Stock Check":   str(stock_check),
        "Remarks":       remarks,
        "Max Setup":     max_action,
        "Update 0":      push_0,
    }


def run_sku_validation(data, country):
    content   = data.get("content",   pd.DataFrame())
    tc_inv    = data.get("tc_inv",    pd.DataFrame())
    zecom     = data.get("zecom",     pd.DataFrame())
    all_df    = data.get("all_file",  pd.DataFrame())
    exclusion = data.get("exclusion", pd.DataFrame())

    excl_map    = _build_excl_map(exclusion)
    article_map = _build_article_map(content)
    tc_map      = _build_tc_map(tc_inv)
    launch_map  = _build_launch_map(zecom)

    mp_sources = {
        "Lazada " + country: data.get("lazada", pd.DataFrame()),
        "Zalora " + country: data.get("zalora", pd.DataFrame()),
    }

    rows = []
    for mp_name, df in mp_sources.items():
        if df is None or df.empty or "SKU" not in df.columns:
            continue

        apply_buffer = _needs_buffer(mp_name, country)
        ecom_map  = _build_ecom_map(zecom, mp_name)
        stock_map = _build_stock_map(all_df, apply_buffer)

        for _, r in df.iterrows():
            sku        = _safe_str(r.get("SKU", ""))
            mp_status  = _safe_str(r.get("MP Status", "Unknown"))
            mp_stock   = _safe_num(r.get("MP Stock", 0))
            article_no = article_map.get(sku, "")
            ecom_st    = ecom_map.get(article_no, "Inactive") if article_no else "Inactive"
            tc_data    = tc_map.get(sku, {"TC Status": "Unknown", "Max 0": "No"})
            sd         = stock_map.get(sku, {"TC Stock": 0.0, "Reserved Stock": 0.0})
            excl_lbl   = excl_map.get(article_no, "") if article_no else ""
            launch_dt  = launch_map.get(article_no, "") if article_no else ""

            result = _sku_logic(
                mp_status=mp_status,
                mp_stock=mp_stock,
                ecom_status=ecom_st,
                tc_status=tc_data["TC Status"],
                tc_stock=sd["TC Stock"],
                reserved=sd["Reserved Stock"],
                max_0=tc_data["Max 0"],
                article_no=article_no,
                excl_map=excl_map,
            )
            rows.append({
                "Marketplace":    mp_name,
                "Seller SKU":     sku,
                "Article No":     article_no,
                "MP Status":      mp_status,
                "TC Status":      _normalise_status(tc_data["TC Status"]),
                "e-com (Yes/No)": "Yes" if ecom_st == "Active" else "No",
                "ECOM Status":    ecom_st,
                "Launch Date":    launch_dt,
                "Exclusion":      excl_lbl,
                "MP Stock":       mp_stock,
                "TC Stock":       sd["TC Stock"],
                "Reserved Stock": sd["Reserved Stock"],
                "Max 0":          tc_data["Max 0"],
                **result,
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── PID-level logic (Shopee + TikTok) ────────────────────────────────────────

def run_pid_validation(data, country):
    content   = data.get("content",   pd.DataFrame())
    tc_inv    = data.get("tc_inv",    pd.DataFrame())
    zecom     = data.get("zecom",     pd.DataFrame())
    all_df    = data.get("all_file",  pd.DataFrame())
    exclusion = data.get("exclusion", pd.DataFrame())

    excl_map    = _build_excl_map(exclusion)
    article_map = _build_article_map(content)
    tc_map      = _build_tc_map(tc_inv)
    launch_map  = _build_launch_map(zecom)

    mp_sources = {
        "Shopee " + country: data.get("shopee", pd.DataFrame()),
    }
    if country == "MY":
        mp_sources["TikTok MY"] = data.get("tiktok", pd.DataFrame())

    rows = []

    for mp_name, df in mp_sources.items():
        if df is None or df.empty or "SKU" not in df.columns:
            continue

        apply_buffer = _needs_buffer(mp_name, country)
        ecom_map  = _build_ecom_map(zecom, mp_name)
        stock_map = _build_stock_map(all_df, apply_buffer)

        # ── Step 1: Enrich each SKU row ───────────────────────────────────
        enriched = []
        for _, r in df.iterrows():
            sku       = _safe_str(r.get("SKU", ""))
            pid       = _safe_str(r.get("Product ID", sku))
            mp_status = _safe_str(r.get("MP Status", "Unknown"))
            mp_stock  = _safe_num(r.get("MP Stock", 0))
            art       = article_map.get(sku, "")
            ecom_st   = ecom_map.get(art, "Inactive") if art else "Inactive"
            td        = tc_map.get(sku, {"TC Status": "Unknown", "Max 0": "No"})
            sd        = stock_map.get(sku, {"TC Stock": 0.0, "Reserved Stock": 0.0})
            excl_lbl  = excl_map.get(art, "") if art else ""
            launch_dt = launch_map.get(art, "") if art else ""
            enriched.append({
                "SKU":            sku,
                "Product ID":     pid,
                "MP Status":      mp_status,
                "MP Stock":       mp_stock,
                "Article No":     art,
                "Ecom Status":    ecom_st,
                "TC Status":      td["TC Status"],
                "Max 0":          td["Max 0"],
                "TC Stock":       sd["TC Stock"],
                "Reserved Stock": sd["Reserved Stock"],
                "Exclusion":      excl_lbl,
                "Launch Date":    launch_dt,
            })

        enriched_df = pd.DataFrame(enriched)
        if enriched_df.empty:
            continue

        # ── Step 2: Dual Status per Product ID ───────────────────────────
        dual_map = {}
        for pid, grp in enriched_df.groupby("Product ID", dropna=False):
            statuses = set(grp["Ecom Status"].unique())
            dual_map[_safe_str(pid)] = (
                2 if ("Active" in statuses and "Inactive" in statuses) else 1
            )

        # ── Step 3: Consolidated TC Stock per Product ID ──────────────────
        consolidated_map = (
            enriched_df.groupby("Product ID")["TC Stock"].sum().to_dict()
        )

        # ── Step 4: Per-SKU output row ────────────────────────────────────
        for _, r in enriched_df.iterrows():
            sku        = r["SKU"]
            pid        = r["Product ID"]
            mp_status  = r["MP Status"]
            mp_stock   = r["MP Stock"]
            article_no = r["Article No"]
            ecom_st    = r["Ecom Status"]
            tc_status  = r["TC Status"]
            max_0      = r["Max 0"]
            tc_stock   = r["TC Stock"]
            reserved   = r["Reserved Stock"]
            excl_lbl   = r["Exclusion"]
            launch_dt  = r["Launch Date"]

            dual_status     = dual_map.get(_safe_str(pid), 1)
            consolidated_tc = consolidated_map.get(pid, 0.0)
            ecom_yn         = "Yes" if ecom_st == "Active" else "No"

            excl = _apply_exclusion(article_no, consolidated_tc, excl_map, max_0)
            if excl:
                final_status, comment, max_action = excl
            else:
                if dual_status == 1:
                    if ecom_st == "Inactive":
                        final_status = "Inactive"
                        comment = "Due to Ecom No"
                    elif consolidated_tc == 0:
                        final_status = "Inactive"
                        comment = "Due to 0 Stock"
                    else:
                        final_status = "Active"
                        comment = "Ecom Yes with Stock"
                else:
                    if consolidated_tc == 0:
                        final_status = "Inactive"
                        comment = "Due to 0 Stock"
                    elif ecom_st == "Active":
                        final_status = "Active"
                        comment = "Ecom Yes with Stock"
                    else:
                        final_status = "Active"
                        comment = "Set max"

                max_action = ""
                if comment in ("Due to Ecom No", "Set max") and max_0 == "No":
                    max_action = "Set max"
                elif comment == "Ecom Yes with Stock" and max_0 == "Yes":
                    max_action = "Remove max"
                elif comment == "Due to 0 Stock":
                    if ecom_yn == "Yes" and max_0 == "Yes":
                        max_action = "Remove max"
                    elif ecom_yn in ("No", "") and max_0 == "No":
                        max_action = "Set max"

            mp_norm  = _normalise_status(mp_status)
            tc_norm  = _normalise_status(tc_status)
            fin_norm = final_status

            final_check = (mp_norm == tc_norm == fin_norm)
            stock_check = (mp_stock == tc_stock)

            if not final_check:
                remarks = "Update status to " + final_status
            elif not stock_check:
                if final_status == "Active":
                    if comment == "Set max":
                        remarks = "Set max product"
                    elif reserved != 0:
                        remarks = "Due to Reserved Stock"
                    else:
                        remarks = "Make Impact"
                else:
                    remarks = "Stock not pushed due to Inactive Status"
            else:
                remarks = "All Good"

            push_0 = "Yes" if (tc_stock <= 0 and mp_stock > 0) else ""

            rows.append({
                "Marketplace":          mp_name,
                "SellerSku":            sku,
                "Product ID":           pid,
                "Article No":           article_no,
                "MP Status":            mp_status,
                "TC Status":            _normalise_status(tc_status),
                "e-com (Yes/No)":       ecom_yn,
                "ECOM Status":          ecom_st,
                "Launch Date":          launch_dt,
                "Exclusion":            excl_lbl,
                "Final Status":         final_status,
                "Comments":             comment,
                "Final Check":          str(final_check),
                "Dual Status":          dual_status,
                "Consolidated SUM QTY": consolidated_tc,
                "MP Stock":             mp_stock,
                "TC Stock":             tc_stock,
                "Reserved Stock":       reserved,
                "Max 0":                max_0,
                "Stock Check":          str(stock_check),
                "Remarks":              remarks,
                "Max Setup":            max_action,
                "Update 0":             push_0,
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame()
