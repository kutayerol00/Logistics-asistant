import streamlit as st
import pandas as pd
import re
import io
import plotly.express as px 

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
    /* Genel Buton ve Kart Stilleri */
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        height: 3.5em;
        font-weight: bold;
    }
    
    /* DRAG & DROP ALANINI ZORLA BOYAMA VE BÜYÜTME */
    /* 1. Ana çerçeve ve arka plan */
    [data-testid="stFileUploader"] section {
        min-height: 500px !important;
        background-color: #dee2e6 !important; /* Daha koyu ve belirgin gri */
        border: 3px dashed #007bff !important;
        border-radius: 20px !important;
    }

    /* 2. İç kısımdaki boşluğu ve beyazlığı yok etme */
    [data-testid="stFileUploader"] section > div {
        background-color: transparent !important; 
    }

    /* 3. Streamlit'in içindeki küçük yazı ve ikon alanlarını boyama */
    div[data-testid="stFileUploaderDropzone"] {
        background-color: #dee2e6 !important; /* Kutuyla aynı renk */
        min-height: 500px !important;
    }

    /* 4. Mouse ile üzerine gelindiğinde */
    [data-testid="stFileUploader"] section:hover {
        background-color: #ced4da !important; /* Hover durumunda bir tık daha koyu */
        border-color: #0056b3 !important;
    }

    /* Yazıların okunabilirliği için renk ayarı */
    [data-testid="stFileUploader"] section div div {
        color: #212529 !important;
    }

    /* Küçük Bilgilendirme Metni */
    [data-testid="stFileUploader"] label {
        font-size: 1.2rem !important;
        font-weight: bold !important;
    }
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
    if re.search(r'40\s*(HC|HQ|H/C)', row_str): return "40HC"
    if re.search(r'45\s*(HC|HQ|FT|\'|")', row_str): return "45HC"
    if re.search(r'20\s*(DC|GP|DV|FT|\'|")', row_str): return "20DC"
    if re.search(r'40\s*(DC|GP|DV|FT|\'|")', row_str): return "40DC"
    return ""

def extract_vessel_info_smart(row, current_v_v_col):
    for val in row.values:
        val_str = str(val).strip()
        if "=>" in val_str:
            return val_str 
    if current_v_v_col:
        val = str(row[current_v_v_col]).strip()
        if val.upper() not in ['NAN', 'NONE', '']:
            return val
    return ""

def process_smart_rows(df):
    mbl_col_name = next((c for c in df.columns if "MB/L" in str(c).upper() or "MASTER" in str(c).upper()), None)
    vv_col_name = next((c for c in df.columns if "V/V" in str(c).upper() or "VESSEL" in str(c).upper()), None)
    
    new_rows = []
    skipped_rows = [] 
    
    for _, row in df.iterrows():
        mbl_val = ""
        if mbl_col_name:
            raw_mbl = str(row[mbl_col_name]).upper().strip()
            if raw_mbl not in ['NAN', 'NONE', '', 'NA', 'UNKNOWN_COL']:
                mbl_val = raw_mbl
        
        containers = extract_container_from_full_row(row)
        ctype = extract_volume_from_full_row(row)
        vessel_val = extract_vessel_info_smart(row, vv_col_name)

        if mbl_val and containers:
            for cntr in containers:
                teu_val = ''
                if '40' in ctype or '45' in ctype: teu_val = 2
                elif '20' in ctype: teu_val = 1

                row_data = {
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
        else:
            if containers and not mbl_val: skipped_rows.append(row)
            elif mbl_val and not containers: skipped_rows.append(row)

    return pd.DataFrame(new_rows), pd.DataFrame(skipped_rows)

def clean_mbl_column(val):
    val = str(val).upper().strip()
    val = val.replace(" ", "")
    return val

# ==========================================
# 3. YAN MENÜ
# ==========================================

with st.sidebar:
    # HATA DÜZELTİLDİ: width="100" -> width=100 (Integer yapıldı)
    st.image("https://cdn-icons-png.flaticon.com/512/2821/2821854.png", width=100) 
    st.title("Kullanım Kılavuzu")
    st.markdown("""
    1. **Dosyaları Sürükleyin:** Ortadaki alana Excel dosyalarını atın.
    2. **Başlat:** Sistem taramaya başlar.
    3. **Sonuçlar:** - 
       - **Tam Liste:** Birleştirilmiş tüm liste.
       - **Tmaxx Listesi:** Tmaxxe yüklenmeye hazır liste.
       - **Hata Listesi:** Konteyneri veya MBL'i bulunamayanlar.
    ℹ️ **Not:** Eğer bir MBL'in konteyneri herhangi bir dosyada bulunduysa, diğer dosyalardaki hatalı hali **otomatik silinir**.
    """)
    st.markdown("---")
    st.caption("v2.3 - Stable Fix")

# ==========================================
# 4. ANA EKRAN
# ==========================================

st.title("🚢 Lojistik Operasyon Asistanı")
st.markdown("Dağınık Excel dosyalarını birleştirir, **hataları kontrol ederek temizler** ve yüklemeye hazırlar.")

if 'processed_data' not in st.session_state:
    st.session_state['processed_data'] = None
    st.session_state['skipped_data'] = None 
    st.session_state['report_stats'] = {} 
if 'excel_bytes' not in st.session_state:
    st.session_state['excel_bytes'] = None
if 'skipped_bytes' not in st.session_state:
    st.session_state['skipped_bytes'] = None 
if 'csv_bytes' not in st.session_state:
    st.session_state['csv_bytes'] = None

uploaded_files = st.file_uploader("📂 Excel Dosyalarını Buraya Bırakın", type=["xlsx", "xls"], accept_multiple_files=True)

if uploaded_files and st.session_state.get('last_uploaded_files') != uploaded_files:
    st.session_state['processed_data'] = None
    st.session_state['last_uploaded_files'] = uploaded_files

if uploaded_files:
    if st.session_state['processed_data'] is None:
        if st.button("🚀 Analizi Başlat", type="primary"): 
            
            with st.spinner("Dosyalar okunuyor, veriler eşleştiriliyor..."):
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
                    
                    final_skipped_df = pd.DataFrame()
                    if all_skipped_dfs:
                        final_skipped_df = pd.concat(all_skipped_dfs, ignore_index=True).fillna('')

                    cntr_col = "CNTR NO"
                    mbl_col = "MB/L NO"
                    
                    if mbl_col in final_df.columns:
                        final_df[mbl_col] = final_df[mbl_col].apply(clean_mbl_column)
                    
                    if not final_skipped_df.empty and mbl_col in final_skipped_df.columns:
                        final_skipped_df[mbl_col] = final_skipped_df[mbl_col].apply(clean_mbl_column)

                    # ROLL ÖNCELİKLENDİRME
                    def get_priority_score(row):
                        vessel_str = str(row.get('V/V', ''))
                        if '=>' in vessel_str: return 0 
                        return 1

                    final_df['priority_score'] = final_df.apply(get_priority_score, axis=1)
                    
                    raw_count = len(final_df)
                    sort_cols = [cntr_col, mbl_col, 'priority_score'] if mbl_col in final_df.columns else [cntr_col, 'priority_score']
                    subset_cols = [cntr_col, mbl_col] if mbl_col in final_df.columns else [cntr_col]
                    
                    final_df = final_df.sort_values(by=sort_cols, ascending=True)
                    final_df = final_df.drop_duplicates(subset=subset_cols, keep='first')
                    final_df = final_df.drop(columns=['priority_score'])
                    
                    dropped_duplicates = raw_count - len(final_df)

                    # === ÇAPRAZ KONTROL (CROSS CHECK) ===
                    if not final_skipped_df.empty and mbl_col in final_df.columns and mbl_col in final_skipped_df.columns:
                        found_mbls = set(final_df[mbl_col].unique())
                        final_skipped_df = final_skipped_df[~final_skipped_df[mbl_col].isin(found_mbls)]

                    final_count = len(final_df)

                    # ÇIKTILAR
                    output_excel = io.BytesIO()
                    with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
                        final_df.to_excel(writer, index=False, sheet_name='Sheet1')
                        workbook = writer.book
                        worksheet = writer.sheets['Sheet1']
                        red_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
                        try: col_idx = final_df.columns.get_loc(cntr_col)
                        except: col_idx = 0
                        
                        def col_num_to_letter(n):
                            string = ""
                            while n > 0:
                                n, remainder = divmod(n - 1, 26)
                                string = chr(65 + remainder) + string
                            return string
                        xlsx_col_letter = col_num_to_letter(col_idx + 1)
                        end_row = len(final_df) + 1
                        worksheet.conditional_format(f"{xlsx_col_letter}2:{xlsx_col_letter}{end_row}", {
                            'type': 'formula',
                            'criteria': f'=COUNTIF(${xlsx_col_letter}$2:${xlsx_col_letter}${end_row}, {xlsx_col_letter}2)>1',
                            'format': red_format
                        })
                    output_excel.seek(0)

                    skipped_bytes = None
                    if not final_skipped_df.empty:
                        skipped_buffer = io.BytesIO()
                        with pd.ExcelWriter(skipped_buffer, engine='xlsxwriter') as writer:
                            final_skipped_df.to_excel(writer, index=False, sheet_name='Eksik_Veriler')
                        skipped_buffer.seek(0)
                        skipped_bytes = skipped_buffer

                    if "VOL" not in final_df.columns: final_df["VOL"] = ""
                    tmaxx_df = final_df[["CNTR NO", "VOL"]].copy()
                    tmaxx_df.columns = ['Container No', 'Container Type']
                    tmaxx_df = tmaxx_df[tmaxx_df['Container No'] != '']
                    output_csv = tmaxx_df.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')

                    st.session_state['processed_data'] = final_df
                    st.session_state['skipped_data'] = final_skipped_df
                    st.session_state['excel_bytes'] = output_excel
                    st.session_state['skipped_bytes'] = skipped_bytes
                    st.session_state['csv_bytes'] = output_csv
                    st.session_state['report_stats'] = {
                        'skipped': len(final_skipped_df),
                        'duplicates': dropped_duplicates,
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
    
    st.write("")
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Toplam Konteyner", stats['final'], "✅ Hazır")
    c2.metric("Birleştirilen / Silinen", stats['duplicates'], "🗑️ Temiz")
    c3.metric("Eksik Veri (Kalan)", stats['skipped'], "⚠️ İncele" if stats['skipped'] > 0 else "Normal")
    
    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["📊 Grafikler", "📥 İndir", "👀 Liste"])

    with tab1:
        if not final_df.empty:
            col_graph1, col_graph2 = st.columns(2)
            with col_graph1:
                st.subheader("Gemi Yükü")
                plot_df = final_df.copy()
                plot_df['V/V'] = plot_df['V/V'].replace('', 'Belirsiz')
                fig_vessel = px.pie(plot_df, names='V/V', title='Gemi Dağılımı', hole=0.4)
                # UYARI DÜZELTİLDİ: use_container_width=True
                st.plotly_chart(fig_vessel, key="chart1", use_container_width=True) 
            with col_graph2:
                st.subheader("Konteyner Tipleri")
                plot_df['VOL'] = plot_df['VOL'].replace('', 'Belirsiz')
                fig_vol = px.bar(plot_df['VOL'].value_counts().reset_index(), x='VOL', y='count', title='Tip Dağılımı', labels={'count':'Adet', 'VOL':'Tip'})
                # UYARI DÜZELTİLDİ: use_container_width=True
                st.plotly_chart(fig_vol, key="chart2", use_container_width=True)
        else:
            st.info("Veri yok.")

    with tab2:
        st.subheader("Dosyaları Al")
        col_d1, col_d2, col_d3 = st.columns(3)
        
        with col_d1:
            st.download_button(
                label="📥 1. Temiz Birleştirilmiş Liste (Excel)",
                data=st.session_state['excel_bytes'],
                file_name="BIRLESTIRILMIS_LISTE.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                # use_container_width=True butonlar için her sürümde çalışmayabilir, CSS ile zaten %100 yapıldı.
            )
        
        with col_d2:
            st.download_button(
                label="📤 2. TMAXX Uyumlu Yükleme Dosyası (CSV)",
                data=st.session_state['csv_bytes'],
                file_name="TMAXX_YUKLEME.csv",
                mime="text/csv",
            )
        
        with col_d3:
            if st.session_state['skipped_bytes']:
                st.download_button(
                    label="⚠️ 3. Hatalı Kayıtlar",
                    data=st.session_state['skipped_bytes'],
                    file_name="EKSIK_VERILER.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                st.success("Hata yok! Harika! 🎉")

    with tab3:
        # UYARI DÜZELTİLDİ: width="stretch" (Log dosyası bunu istediği için)
        try:
            st.dataframe(final_df, use_container_width=True)
        except:
            st.dataframe(final_df) # Eski versiyonlar için fallback
    
    st.markdown("---")
    if st.button("🔄 Sıfırla"):
        for key in st.session_state.keys():
            del st.session_state[key]

        st.rerun()






