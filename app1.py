import streamlit as st
import pandas as pd
import re
import io
import plotly.express as px
import uuid

# ==========================================
# 1. AYARLAR VE STİL
# ==========================================
st.set_page_config(
    page_title="Lojistik Operasyon Asistanı", 
    page_icon="🚢", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stButton>button { width: 100%; border-radius: 8px; height: 3.2em; font-weight: bold; transition: all 0.3s ease; }
    [data-testid="stFileUploader"] section { padding: 3rem 2rem !important; background-color: rgba(255, 255, 255, 0.03) !important; border: 2px dashed rgba(255, 255, 255, 0.2) !important; border-radius: 16px !important; min-height: 250px !important; display: flex !important; align-items: center !important; justify-content: center !important; transition: all 0.3s ease-in-out !important; }
    [data-testid="stFileUploader"] section > div { background-color: transparent !important; }
    [data-testid="stFileUploader"] section:hover { background-color: rgba(255, 255, 255, 0.06) !important; border-color: #4da6ff !important; box-shadow: 0px 0px 15px rgba(77, 166, 255, 0.15) !important; }
    [data-testid="stFileUploader"] section div div { color: #b0bec5 !important; font-size: 1.05rem !important; }
    [data-testid="stFileUploader"] section svg { fill: #4da6ff !important; width: 60px !important; height: 60px !important; margin-bottom: 10px !important; }
    [data-testid="stFileUploader"] section button { background-color: #4da6ff !important; color: #121212 !important; font-weight: 600 !important; border-radius: 8px !important; border: none !important; padding: 0.5rem 1.5rem !important; margin-top: 15px !important; transition: all 0.2s ease !important; }
    [data-testid="stFileUploader"] section button:hover { background-color: #2b8ce6 !important; color: white !important; }
    .stFileUploader label { font-size: 1.1rem !important; font-weight: 600 !important; margin-bottom: 0.8rem !important; }
    
    .color-box {
        display: inline-block;
        width: 15px;
        height: 15px;
        border-radius: 3px;
        margin-right: 8px;
        vertical-align: middle;
    }
    .red-box { background-color: #FFC7CE; border: 1px solid #9C0006; }
    .orange-box { background-color: #FCE4D6; border: 1px solid #C65911; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. YARDIMCI FONKSİYONLAR
# ==========================================

def make_columns_unique(columns):
    seen = {}
    new_columns = []
    for col in columns:
        col_str = str(col).strip()
        if not col_str or col_str.lower() in ['nan', 'none', '']:
            col_str = "Unknown_Col"
        if col_str in seen:
            seen[col_str] += 1
            new_col = f"{col_str}.{seen[col_str]}"
        else:
            seen[col_str] = 0
            new_col = col_str
        new_columns.append(new_col)
    return new_columns

def find_and_set_header(raw_df):
    search_limit = min(30, len(raw_df))
    target_keywords = ["MB/L NO", "BOOKING NO", "POL", "POD", "VOL", "V/V", "CONTAINER", "CNTR"]
    header_idx = -1
    max_score = 0
    for i in range(search_limit):
        row_values = " ".join([str(val).upper() for val in raw_df.iloc[i].values])
        score = sum(1 for keyword in target_keywords if keyword in row_values)
        if score > max_score:
            max_score = score
            header_idx = i
    if header_idx != -1:
        new_header = raw_df.iloc[header_idx]
        df = raw_df.iloc[header_idx + 1:].copy()
        df.columns = make_columns_unique(new_header)
        return df
    return None

def extract_container_from_full_row(row):
    row_str = " ".join([str(val).upper() for val in row.values])
    row_str = row_str.replace('/', ' ').replace(',', ' ').replace('&', ' ').replace(';', ' ').replace('-', ' ').replace(':', ' ')
    matches = re.findall(r'\b[A-Z]{4}\s*\d{5,8}\b', row_str)
    valid_containers = []
    for m in matches:
        clean_m = m.replace(" ", "").replace("\t", "")
        if 9 <= len(clean_m) <= 12:
            valid_containers.append(clean_m)
    return valid_containers

def extract_volume_from_full_row(row):
    row_str = " ".join([str(val).upper() for val in row.values])
    types = set()
    if re.search(r'40\s*(HC|HQ|H/C)', row_str): types.add("40HC")
    if re.search(r'45\s*(HC|HQ|FT|\'|")', row_str): types.add("45HC")
    if re.search(r'20\s*(DC|GP|DV|ST|FT|\'|")', row_str): types.add("20DC")
    if re.search(r'40\s*(DC|GP|DV|ST)', row_str): types.add("40DC")
    elif re.search(r'40\s*(\'|")', row_str) and "40HC" not in types: types.add("40DC")
    if len(types) > 1: return "⚠️ ŞÜPHELİ (KARIŞIK TİP)"
    elif len(types) == 1: return list(types)[0]
    else: return ""

def extract_vessel_info_smart(row, current_v_v_col):
    for val in row.values:
        val_str = str(val).strip()
        if "=>" in val_str: return val_str 
    if current_v_v_col:
        val = str(row[current_v_v_col]).strip()
        if val.upper() not in ['NAN', 'NONE', '']: return val
    return ""

def clean_mbl_column(val):
    return str(val).upper().strip().replace(" ", "")

def process_smart_rows(df):
    mbl_col_name = next((c for c in df.columns if "MB/L" in str(c).upper() or "MASTER" in str(c).upper()), None)
    vv_col_name = next((c for c in df.columns if "V/V" in str(c).upper() or "VESSEL" in str(c).upper()), None)
    
    new_rows = []
    skipped_rows = [] 
    
    for _, row in df.iterrows():
        if row.astype(str).str.strip().replace(['NAN', 'NONE', ''], pd.NA).isna().all():
            continue
        input_row_id = str(uuid.uuid4()) 
        
        mbl_val = ""
        if mbl_col_name:
            raw_mbl = str(row[mbl_col_name]).upper().strip()
            if raw_mbl not in ['NAN', 'NONE', '', 'NA', 'UNKNOWN_COL']:
                mbl_val = clean_mbl_column(raw_mbl)
        
        containers = extract_container_from_full_row(row)
        ctype = extract_volume_from_full_row(row)
        vessel_val = extract_vessel_info_smart(row, vv_col_name)

        if mbl_val and containers:
            for cntr in containers:
                teu_val = ''
                if "ŞÜPHELİ" in ctype: teu_val = ""
                elif '40' in ctype or '45' in ctype: teu_val = 2
                elif '20' in ctype: teu_val = 1
                row_data = {
                    "INPUT_ROW_ID": input_row_id, 
                    "MB/L NO": mbl_val, "CNTR NO": cntr,
                    "VOL": ctype if ctype else "Unknown", "TEU": teu_val, "V/V": vessel_val
                }
                for col in ["POL", "POD", "BOOKING NO"]:
                     actual_col = next((c for c in df.columns if col in str(c).upper()), None)
                     if actual_col: row_data[col] = str(row[actual_col])
                new_rows.append(row_data)
        else:
            row_dict = row.to_dict()
            row_dict['HATA_NEDENI'] = "EKSİK VERİ"
            skipped_rows.append(row_dict)
    return pd.DataFrame(new_rows), pd.DataFrame(skipped_rows)

# ==========================================
# 3. ANA UYGULAMA MANTIĞI
# ==========================================

if 'processed_data' not in st.session_state:
    st.session_state['processed_data'] = None
    st.session_state['report_stats'] = {} 
    st.session_state['tmaxx_files'] = {}

with st.sidebar:
    st.title("Kullanım Kılavuzu")
    st.markdown("CSV çıktıları artık **başlıksız** ve **noktalı virgül (;)** ayracıyla üretilmektedir.")

st.title("🚢 Lojistik Operasyon Asistanı")

uploaded_files = st.file_uploader("📂 Excel Dosyalarını Buraya Bırakın", type=["xlsx", "xls"], accept_multiple_files=True)

if uploaded_files:
    if st.button("🚀 Analizi Başlat", type="primary"): 
        with st.spinner("İşleniyor..."):
            all_dfs = []
            for uploaded_file in uploaded_files:
                xls = pd.read_excel(uploaded_file, sheet_name=None, header=None, dtype=str)
                for sheet_name, raw_df in xls.items():
                    df = find_and_set_header(raw_df)
                    if df is not None:
                        processed_df, _ = process_smart_rows(df)
                        if not processed_df.empty:
                            processed_df['KAYNAK_SAYFA'] = sheet_name
                            all_dfs.append(processed_df)

            if all_dfs:
                final_df = pd.concat(all_dfs, ignore_index=True).fillna('')
                
                # Hata Kontrolleri
                final_df['IS_CNTR_DUPLICATE'] = final_df.duplicated(subset=['CNTR NO'], keep=False)
                final_df['IS_INVALID_LENGTH'] = final_df['CNTR NO'].str.replace(r'\s+', '', regex=True).str.len() != 11
                
                # CSV OLUŞTURMA (BAŞLIKSIZ VE NOKTALI VİRGÜLLÜ)
                tmaxx_files_dict = {}
                for sheet_name in final_df['KAYNAK_SAYFA'].unique():
                    sheet_df = final_df[final_df['KAYNAK_SAYFA'] == sheet_name].copy()
                    
                    # Tmaxx Formatı: Container No ; Container Type
                    tmaxx_export = sheet_df[["CNTR NO", "VOL"]].copy()
                    
                    if not tmaxx_export.empty:
                        # header=False: Başlık satırını siler
                        # sep=';': Ayracı noktalı virgül yapar
                        csv_buffer = io.StringIO()
                        tmaxx_export.to_csv(csv_buffer, index=False, header=False, sep=';', encoding='utf-8')
                        tmaxx_files_dict[f"{sheet_name}.csv"] = csv_buffer.getvalue().encode('utf-8')

                # Excel Çıktısı (Tam Liste için)
                excel_buffer = io.BytesIO()
                with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                    final_df.to_excel(writer, index=False, sheet_name='Sonuc')
                excel_buffer.seek(0)

                st.session_state['processed_data'] = final_df
                st.session_state['excel_bytes'] = excel_buffer
                st.session_state['tmaxx_files'] = tmaxx_files_dict
                st.rerun()

# ==========================================
# 4. İNDİRME ALANI
# ==========================================
if st.session_state['processed_data'] is not None:
    st.success("Analiz tamamlandı!")
    
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 Tam Listeyi İndir (Excel)", st.session_state['excel_bytes'], "BIRLESTIRILMIS_LISTE.xlsx")
    
    with col2:
        st.markdown("##### 📤 Tmaxx Dosyaları (Başlıksız & Noktalı Virgüllü)")
        for file_name, file_bytes in st.session_state['tmaxx_files'].items():
            st.download_button(f"📥 {file_name}", file_bytes, file_name, mime="text/csv")

    st.dataframe(st.session_state['processed_data'], use_container_width=True)
