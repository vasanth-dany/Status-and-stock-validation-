import io
import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Status Validation Analyzer",
    page_icon="chart_with_upwards_trend",
    layout="wide",
)

from utils.file_loaders import load_all_files
from utils.validators import run_sku_validation, run_pid_validation
from utils.report_generator import generate_status_report
from utils.styles import inject_css

inject_css()


def show_df(df):
    if df is None or df.empty:
        st.warning("No data to display.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Rows", len(df))
    if "Final Status" in df.columns:
        c2.metric("Active",   int((df["Final Status"] == "Active").sum()))
        c3.metric("Inactive", int((df["Final Status"] == "Inactive").sum()))
    if "Final Check" in df.columns:
        c4.metric("True Checks", int((df["Final Check"] == "True").sum()))
    st.dataframe(df, width="stretch", height=500)


with st.sidebar:
    st.markdown("## Configuration")
    country = st.selectbox("Select Country", ["SG", "MY", "PH"])
    st.markdown("---")

    with st.expander("Lazada " + country):
        laz = st.file_uploader(
            "Lazada File", type=["xlsx", "xls", "csv"], key="laz"
        )

    with st.expander("Shopee " + country):
        sh_stk = st.file_uploader(
            "Shopee Stock", type=["xlsx", "xls", "csv", "zip"], key="sh_stk"
        )
        sh_sts = st.file_uploader(
            "Shopee Status", type=["xlsx", "xls", "csv", "zip"], key="sh_sts"
        )

    with st.expander("Zalora " + country):
        zal_stk = st.file_uploader(
            "Zalora Stock", type=["xlsx", "xls", "csv"], key="zal_stk"
        )
        zal_sts = st.file_uploader(
            "Zalora Status", type=["xlsx", "xls", "csv"], key="zal_sts"
        )

    tt_act = None
    tt_ina = None
    if country == "MY":
        with st.expander("TikTok MY"):
            tt_act = st.file_uploader(
                "TikTok Active File", type=["xlsx", "xls", "csv"], key="tt_act"
            )
            tt_ina = st.file_uploader(
                "TikTok Inactive File", type=["xlsx", "xls", "csv"], key="tt_ina"
            )

    with st.expander("Reference Files"):
        cnt  = st.file_uploader(
            "Content File", type=["xlsx", "xls", "csv"], key="cnt"
        )
        tc   = st.file_uploader(
            "TC Inventory", type=["xlsx", "xls", "csv"], key="tc"
        )
        zec  = st.file_uploader(
            "zEcom File (header row 3 for PH / row 4 for SG & MY)",
            type=["xlsx", "xls", "csv"], key="zec"
        )
        alf  = st.file_uploader(
            "ALL File", type=["xlsx", "xls", "csv"], key="alf"
        )
        excl = st.file_uploader(
            "Exclusion List", type=["xlsx", "xls", "csv"], key="excl"
        )

    st.markdown("---")
    run_btn = st.button("Run Validation", use_container_width=True, type="primary")


st.title("Status Validation Analyzer")
st.write(
    "Country: " + country +
    "  |  Upload files in the sidebar then click Run Validation."
)

tab1, tab2, tab3, tab4 = st.tabs([
    "Status Report",
    "SKU Validation",
    "PID Validation",
    "Downloads",
])

if run_btn:
    with st.spinner("Loading files..."):
        try:
            data = load_all_files(
                country=country,
                lazada_file=laz,
                shopee_stock_file=sh_stk,
                shopee_status_file=sh_sts,
                zalora_stock_file=zal_stk,
                zalora_status_file=zal_sts,
                tiktok_active_file=tt_act,
                tiktok_inactive_file=tt_ina,
                content_file=cnt,
                tc_inv_file=tc,
                zecom_file=zec,
                all_file=alf,
                exclusion_file=excl,
            )
            st.session_state["data"]    = data
            st.session_state["country"] = country

            parts = []
            for k, v in data.items():
                if isinstance(v, pd.DataFrame) and not v.empty:
                    parts.append(k + ":" + str(len(v)))
            st.success("Loaded: " + "  |  ".join(parts))

            with st.expander("Column names per file"):
                for k, v in data.items():
                    if isinstance(v, pd.DataFrame) and not v.empty:
                        st.write(k + " -> " + str(list(v.columns)))

        except Exception as e:
            st.error("Load error: " + str(e))
            st.exception(e)
            st.stop()

    with st.spinner("Running validations..."):
        try:
            d = st.session_state["data"]
            c = st.session_state["country"]
            st.session_state["sr"] = generate_status_report(d, c)
            st.session_state["sk"] = run_sku_validation(d, c)
            st.session_state["pi"] = run_pid_validation(d, c)
            st.success("Validation complete!")
        except Exception as e:
            st.error("Validation error: " + str(e))
            st.exception(e)
            st.stop()


with tab1:
    if "sr" in st.session_state:
        df = st.session_state["sr"].copy()
        rc = st.session_state.get("country", country)
        st.markdown("### Status Report - " + rc)
        if not df.empty and "Marketplace" in df.columns:
            opts = sorted(df["Marketplace"].unique())
            sel  = st.multiselect(
                "Filter by Marketplace", opts, default=opts, key="f1"
            )
            df = df[df["Marketplace"].isin(sel)]
        show_df(df)
    else:
        st.info("Run validation to see results.")

with tab2:
    if "sk" in st.session_state:
        df = st.session_state["sk"].copy()
        rc = st.session_state.get("country", country)
        st.markdown("### SKU Validation - " + rc)
        if not df.empty:
            c1, c2 = st.columns(2)
            if "Final Check" in df.columns:
                sel = c1.multiselect(
                    "Final Check", ["True", "False"],
                    default=["True", "False"], key="f2"
                )
                df = df[df["Final Check"].isin(sel)]
            if "Marketplace" in df.columns:
                opts = sorted(df["Marketplace"].unique())
                sel2 = c2.multiselect(
                    "Marketplace", opts, default=opts, key="f2b"
                )
                df = df[df["Marketplace"].isin(sel2)]
        show_df(df)
    else:
        st.info("Run validation to see results.")

with tab3:
    if "pi" in st.session_state:
        df = st.session_state["pi"].copy()
        rc = st.session_state.get("country", country)
        st.markdown("### PID Validation - " + rc)
        if not df.empty:
            c1, c2 = st.columns(2)
            if "Final Check" in df.columns:
                sel = c1.multiselect(
                    "Final Check", ["True", "False"],
                    default=["True", "False"], key="f3"
                )
                df = df[df["Final Check"].isin(sel)]
            if "Dual Status" in df.columns:
                ds_opts = sorted(df["Dual Status"].unique())
                sel2 = c2.multiselect(
                    "Dual Status", ds_opts, default=ds_opts, key="f3b"
                )
                df = df[df["Dual Status"].isin(sel2)]
        show_df(df)
    else:
        st.info("Run validation to see results.")

with tab4:
    if "sr" in st.session_state:
        rc = st.session_state.get("country", country)
        sr = st.session_state["sr"]
        sk = st.session_state["sk"]
        pi = st.session_state["pi"]

        sheets = {}
        if not sr.empty:
            sheets["Status Report"]  = sr
        if not sk.empty:
            sheets["SKU Validation"] = sk
        if not pi.empty:
            sheets["PID Validation"] = pi

        if sheets:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                for nm, sdf in sheets.items():
                    sdf.to_excel(writer, sheet_name=nm, index=False)
            st.download_button(
                "Download Excel Report",
                data=buf.getvalue(),
                file_name="report_" + rc + ".xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.warning("No data to download. Run validation first.")

        st.markdown("#### Preview Sheet")
        choice = st.radio(
            "Select sheet",
            ["Status Report", "SKU Validation", "PID Validation"],
            horizontal=True,
        )
        pm = {"Status Report": sr, "SKU Validation": sk, "PID Validation": pi}
        pv = pm[choice]
        if pv.empty:
            st.info("No data for this sheet.")
        else:
            st.dataframe(pv, width="stretch", height=400)
    else:
        st.info("Run validation first.")
