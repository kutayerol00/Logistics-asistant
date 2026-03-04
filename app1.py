import streamlit as st
import pandas as pd
import re
import io
import plotly.express as px
import uuid  # Satır kimlikleri için eklendi

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
    matches = re.findall(r'\b[A-Z]{4}\s*\d{6,7}\b', row_str)
    
    valid_containers = []
    for m in matches:
        clean_m = m.replace(" ", "").replace("\t", "")
        if 10 <= len(clean_m) <= 11:
            if clean_m not in valid_containers:
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
        # Tamamen boş satırları atla
        if row.astype(str).str.strip().replace(['NAN', 'NONE', ''], pd.NA).isna().all():
            continue

        input_row_id = str(uuid.uuid4()) # Bu girdi satırı için benzersiz kimlik
        
        mbl_val = ""
        if mbl_col_name:
            raw_mbl = str(row[mbl_col_name]).upper().strip()
            if raw_mbl not in ['NAN', 'NONE', '', 'NA', 'UNKNOWN_COL']:
                mbl_val = clean_mbl_column(raw_mbl)
        
        containers = extract_container_from_full_row(row)
        ctype = extract_volume_from_full_row(row)
        vessel_val = extract_vessel_info_smart(row, vv_col_name)

        # HEM MBL HEM KONTEYNER VARSA NORMAL İŞLE (ÇIKTI ÇOĞALTMA)
        if mbl_val and containers:
            for cntr in containers:
                teu_val = ''
                if "ŞÜPHELİ" in ctype: teu_val = ""
                elif '40' in ctype or '45' in ctype: teu_val = 2
                elif '20' in ctype: teu_val = 1

                row_data = {
                    "INPUT_ROW_ID": input_row_id, # Kimliği kaydet (Girdi dosyasındaki tekrarı anlamak için)
                    "MB/L NO": mbl_val,
                    "CNTR NO": cntr,
                    "VOL": ctype if ctype else "Unknown", 
                    "TEU": teu_val,
                    "V/V": vessel_val
                }
                for col in ["POL", "POD", "BOOKING NO"]:
                     actual_col = next((c for c in df.columns if col in str(c).upper()), None)
                     if actual_col: row_data[col] = str(row[actual_col])
                new_rows.append(row_data)
        
        # BİRİ BİLE EKSİKSE DİREKT HATAYA AT
        else:
            row_dict = row.to_dict()
            if not mbl_val and not containers:
                row_dict['HATA_NEDENI'] = "MBL VE KONTEYNER NO BULUNAMADI"
            elif not mbl_val:
                row_dict['HATA_NEDENI'] = "EKSİK MBL NO"
            else:
                row_dict['HATA_NEDENI'] = "EKSİK KONTEYNER NO"
            
            row_dict['BULUNAN_MBL'] = mbl_val if mbl_val else "YOK"
            row_dict['BULUNAN_CNTR'] = ", ".join(containers) if containers else "YOK"
            skipped_rows.append(row_dict)

    return pd.DataFrame(new_rows), pd.DataFrame(skipped_rows)


# ==========================================
# 3. YAN MENÜ
# ==========================================

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2821/2821854.png", width=100) 
    st.title("Kullanım Kılavuzu")
    st.markdown("""
    1. **Dosyaları Sürükleyin:** Ortadaki alana Excel dosyalarını atın.
    2. **Başlat:** Sistem taramaya başlar.
    3. **Sonuçlar:** - **Tam Liste:** Birleştirilmiş tüm liste.
        - **Tmaxx Listesi:** Her sayfa için ayrı yükleme listesi.
        - **Hata Listesi:** MBL/Konteyneri bulunamayanlar veya listede mükerrer geçen veriler.
    """)
    st.markdown("---")
    st.caption("v2.8 - Girdi Bazlı MBL & Global Konteyner Kontrolü")

# ==========================================
# 4. ANA EKRAN
# ==========================================

st.title("🚢 Lojistik Operasyon Asistanı")
st.markdown("Dağınık Excel dosyalarını birleştirir, **eksik ve mükerrer kayıtları kontrol ederek temizler** ve yüklemeye hazırlar.")

if 'processed_data' not in st.session_state:
    st.session_state['processed_data'] = None
    st.session_state['skipped_data'] = None 
    st.session_state['report_stats'] = {} 
if 'excel_bytes' not in st.session_state: st.session_state['excel_bytes'] = None
if 'skipped_bytes' not in st.session_state: st.session_state['skipped_bytes'] = None 
if 'tmaxx_files' not in st.session_state: st.session_state['tmaxx_files'] = {}

uploaded_files = st.file_uploader("📂 Excel Dosyalarını Buraya Bırakın", type=["xlsx", "xls"], accept_multiple_files=True)

if uploaded_files and st.session_state.get('last_uploaded_files') != uploaded_files:
    st.session_state['processed_data'] = None
    st.session_state['last_uploaded_files'] = uploaded_files

if uploaded_files:
    if st.session_state['processed_data'] is None:
        if st.button("🚀 Analizi Başlat", type="primary"): 
            
            with st.spinner("Dosyalar okunuyor, kontroller yapılıyor..."):
                all_dfs = []
                all_skipped_dfs = [] 
                my_bar = st.progress(0, text="Başlıyor...")

                for i, uploaded_file in enumerate(uploaded_files):
                    try:
                        xls = pd.read_excel(uploaded_file, sheet_name=None, header=None, dtype=str)
                        for sheet_name, raw_df in xls.items():
                            df = find_and_set_header(raw_df)
                            if df is not None:
                                processed_df, skipped_df = process_smart_rows(df)
                                if not processed_df.empty:
                                    processed_df['KAYNAK_DOSYA'] = uploaded_file.name
                                    processed_df['KAYNAK_SAYFA'] = sheet_name
                                    all_dfs.append(processed_df)
                                if not skipped_df.empty:
                                    skipped_df['KAYNAK_DOSYA'] = uploaded_file.name
                                    skipped_df['KAYNAK_SAYFA'] = sheet_name
                                    all_skipped_dfs.append(skipped_df)
                    except Exception as e:
                        st.error(f"Hata ({uploaded_file.name}): {e}")
                    my_bar.progress((i + 1) / len(uploaded_files), text=f"Taranıyor: {uploaded_file.name}")

                if all_dfs:
                    final_df = pd.concat(all_dfs, ignore_index=True).fillna('')
                    final_skipped_df = pd.concat(all_skipped_dfs, ignore_index=True).fillna('') if all_skipped_dfs else pd.DataFrame()

                    raw_count = len(final_df)

                    # === 1. KONTEYNER KONTROLÜ (GLOBAL) ===
                    final_df['IS_CNTR_DUPLICATE'] = final_df.duplicated(subset=['CNTR NO'], keep=False)

                    # === 2. MBL KONTROLÜ (GİRDİ DOSYASI BAZLI) ===
                    # Aynı MBL'in kaç farklı GİRDİ SATIRINDAN (INPUT_ROW_ID) geldiğini sayarız
                    mbl_row_counts = final_df.groupby('MB/L NO')['INPUT_ROW_ID'].nunique()
                    duplicate_mbls = mbl_row_counts[mbl_row_counts > 1].index
                    final_df['IS_MBL_DUPLICATE'] = final_df['MB/L NO'].isin(duplicate_mbls)

                    # Genel Hata Bayrağı
                    final_df['IS_ERROR'] = final_df['IS_CNTR_DUPLICATE'] | final_df['IS_MBL_DUPLICATE']
                    
                    # Hatalı kayıtları tespit edip ayıklayalım (Silmeden Hatalar Listesine Ekliyoruz)
                    error_rows = final_df[final_df['IS_ERROR'] == True].copy()
                    error_count = len(error_rows)
                    
                    if not error_rows.empty:
                        def get_error_reason(row):
                            reasons = []
                            if row['IS_CNTR_DUPLICATE']: reasons.append("TEKRAR EDEN KONTEYNER")
                            if row['IS_MBL_DUPLICATE']: reasons.append("GİRDİDE TEKRAR EDEN MBL")
                            return " + ".join(reasons)
                        
                        error_rows['HATA_NEDENI'] = error_rows.apply(get_error_reason, axis=1)
                        # Bu hataları eksik verilerin tutulduğu hata listesine ekle
                        final_skipped_df = pd.concat([final_skipped_df, error_rows], ignore_index=True).fillna('')

                    final_count = len(final_df)

                    # ÇIKTILAR (1. Birleştirilmiş Liste Excel)
                    output_excel = io.BytesIO()
                    with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
                        # Gereksiz sistem sütunlarını at
                        df_export = final_df.drop(columns=['INPUT_ROW_ID', 'IS_CNTR_DUPLICATE', 'IS_MBL_DUPLICATE', 'IS_ERROR'])
                        df_export.to_excel(writer, index=False, sheet_name='Sheet1')
                        workbook = writer.book
                        worksheet = writer.sheets['Sheet1']
                        red_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
                        
                        # Hatalı/Tekrar edenleri excelde boydan boya kırmızıya boya
                        for row_num, is_err in enumerate(final_df['IS_ERROR']):
                            if is_err: worksheet.set_row(row_num + 1, None, red_format)
                    output_excel.seek(0)

                    # Hatalı Listeyi (3. Excel) Yazma
                    skipped_bytes = None
                    if not final_skipped_df.empty:
                        skipped_buffer = io.BytesIO()
                        with pd.ExcelWriter(skipped_buffer, engine='xlsxwriter') as writer:
                            df_skipped_export = final_skipped_df.drop(columns=['INPUT_ROW_ID', 'IS_CNTR_DUPLICATE', 'IS_MBL_DUPLICATE', 'IS_ERROR'], errors='ignore')
                            df_skipped_export.to_excel(writer, index=False, sheet_name='Hatalar')
                            workbook = writer.book
                            worksheet = writer.sheets['Hatalar']
                            red_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
                            
                            if 'HATA_NEDENI' in df_skipped_export.columns:
                                for row_num, reason in enumerate(df_skipped_export['HATA_NEDENI']):
                                    if "TEKRAR" in str(reason): worksheet.set_row(row_num + 1, None, red_format)
                        skipped_buffer.seek(0)
                        skipped_bytes = skipped_buffer

                    # TMAXX Dosyalarını Her Sayfa İçin Ayrı Üretme (2. Liste)
                    if "VOL" not in final_df.columns: final_df["VOL"] = ""
                    tmaxx_files_dict = {}
                    
                    def get_tmaxx_err_suffix(row):
                        errs = []
                        if row['IS_CNTR_DUPLICATE']: errs.append("CNTR TEKRAR")
                        if row['IS_MBL_DUPLICATE']: errs.append("MBL TEKRAR")
                        return f" [HATA: {' + '.join(errs)}]" if errs else ""

                    if 'KAYNAK_SAYFA' in final_df.columns:
                        for sheet_name in final_df['KAYNAK_SAYFA'].unique():
                            sheet_df = final_df[final_df['KAYNAK_SAYFA'] == sheet_name].copy()
                            tmaxx_df = sheet_df[["CNTR NO", "VOL", "IS_CNTR_DUPLICATE", "IS_MBL_DUPLICATE"]].copy()
                            tmaxx_df['CNTR NO'] = tmaxx_df['CNTR NO'] + tmaxx_df.apply(get_tmaxx_err_suffix, axis=1)
                            
                            tmaxx_df = tmaxx_df[["CNTR NO", "VOL"]]
                            tmaxx_df.columns = ['Container No', 'Container Type']
                            tmaxx_df = tmaxx_df[tmaxx_df['Container No'] != '']
                            
                            if not tmaxx_df.empty:
                                output_csv = tmaxx_df.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')
                                safe_name = str(sheet_name).replace("/", "_").replace("\\", "_")
                                tmaxx_files_dict[f"{safe_name}.csv"] = output_csv

                    # Ekranda göstermek için temiz dataframe
                    display_df = final_df.drop(columns=['INPUT_ROW_ID', 'IS_CNTR_DUPLICATE', 'IS_MBL_DUPLICATE', 'IS_ERROR'])

                    st.session_state['processed_data'] = display_df
                    st.session_state['skipped_data'] = final_skipped_df
                    st.session_state['excel_bytes'] = output_excel
                    st.session_state['skipped_bytes'] = skipped_bytes
                    st.session_state['tmaxx_files'] = tmaxx_files_dict
                    st.session_state['report_stats'] = {
                        'skipped': len(final_skipped_df),
                        'duplicates': error_count,
                        'final': final_count
                    }
                    
                    my_bar.empty()
                    st.balloons()
                    st.rerun()
                else:
                    st.error("❌ Dosyalar okunamadı veya veri bulunamadı.")

# ==========================================
# 5. DASHBOARD
# ==========================================

if st.session_state['processed_data'] is not None:
    stats = st.session_state['report_stats']
    final_df = st.session_state['processed_data']
    suspicious_count = len(final_df[final_df['VOL'] == "⚠️ ŞÜPHELİ (KARIŞIK TİP)"]) if 'VOL' in final_df.columns else 0
    
    st.write("")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Konteyner", stats['final'], "✅ İşlenen")
    c2.metric("Tekrar Eden Hata", stats['duplicates'], "🚨 Mükerrer", delta_color="inverse" if stats['duplicates'] > 0 else "normal")
    c3.metric("Toplam Hatalı Veri", stats['skipped'], "⚠️ İncele" if stats['skipped'] > 0 else "Temiz", delta_color="inverse" if stats['skipped'] > 0 else "normal")
    c4.metric("Şüpheli Kayıt", suspicious_count, "Manuel Kontrol" if suspicious_count > 0 else "Temiz", delta_color="inverse" if suspicious_count > 0 else "normal")
    
    st.markdown("---")

    if stats['duplicates'] > 0:
        st.error(f"🚨 DİKKAT: İşlenen verilerde {stats['duplicates']} adet tekrar hatası (Konteyner veya Girdi Dosyası MBL tekrarı) bulundu! Çıktılarda kırmızı olarak işaretlenmiştir.")

    tab1, tab2, tab3 = st.tabs(["📊 Grafikler", "📥 İndir", "👀 Liste"])

    with tab1:
        if not final_df.empty:
            col_graph1, col_graph2 = st.columns(2)
            with col_graph1:
                st.subheader("Gemi Yükü")
                plot_df = final_df.copy()
                plot_df['V/V'] = plot_df['V/V'].replace('', 'Belirsiz')
                fig_vessel = px.pie(plot_df, names='V/V', title='Gemi Dağılımı', hole=0.4)
                st.plotly_chart(fig_vessel, key="chart1", use_container_width=True) 
            with col_graph2:
                st.subheader("Konteyner Tipleri")
                plot_df['VOL'] = plot_df['VOL'].replace('', 'Belirsiz')
                fig_vol = px.bar(plot_df['VOL'].value_counts().reset_index(), x='VOL', y='count', title='Tip Dağılımı', labels={'count':'Adet', 'VOL':'Tip'})
                st.plotly_chart(fig_vol, key="chart2", use_container_width=True)

    with tab2:
        st.subheader("Dosyaları Al")
        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1:
            st.download_button(label="📥 1. Temiz Birleştirilmiş Liste (Excel)", data=st.session_state['excel_bytes'], file_name="BIRLESTIRILMIS_LISTE.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with col_d2:
            st.markdown("##### 📤 2. Tmaxx Dosyaları (CSV)")
            if st.session_state['tmaxx_files']:
                for file_name, file_bytes in st.session_state['tmaxx_files'].items():
                    st.download_button(label=f"📥 {file_name}", data=file_bytes, file_name=file_name, mime="text/csv", key=f"dl_btn_{file_name}")
        with col_d3:
            if st.session_state['skipped_bytes']:
                st.download_button(label="⚠️ 3. Hatalı Kayıtlar", data=st.session_state['skipped_bytes'], file_name="HATALI_KAYITLAR.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.success("Hata yok! Harika! 🎉")

    with tab3:
        st.dataframe(final_df, use_container_width=True)
    
    st.markdown("---")
    if st.button("🔄 Yeni İşlem Başlat"):
        for key in st.session_state.keys(): del st.session_state[key]
        st.rerun()
