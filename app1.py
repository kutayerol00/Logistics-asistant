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
# FONKSİYONLAR
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


# Ana hesaplama ve çıktı oluşturma fonksiyonu (Düzeltme sonrası tekrar tetiklenebilmesi için ayrıldı)
def run_evaluation_and_outputs():
    final_df = st.session_state['raw_data'].copy()
    final_skipped_df = st.session_state['raw_skipped'].copy()
    
    # 1. Kontroller
    final_df['IS_CNTR_DUPLICATE'] = final_df.duplicated(subset=['CNTR NO'], keep=False)
    mbl_row_counts = final_df.groupby('MB/L NO')['INPUT_ROW_ID'].nunique()
    duplicate_mbls = mbl_row_counts[mbl_row_counts > 1].index
    final_df['IS_MBL_DUPLICATE'] = final_df['MB/L NO'].isin(duplicate_mbls)
    
    final_df['CLEAN_CNTR'] = final_df['CNTR NO'].astype(str).str.replace(r'\s+', '', regex=True)
    final_df['IS_INVALID_LENGTH'] = final_df['CLEAN_CNTR'].str.len() != 11
    final_df['IS_ERROR'] = final_df['IS_CNTR_DUPLICATE'] | final_df['IS_MBL_DUPLICATE'] | final_df['IS_INVALID_LENGTH']
    
    error_rows = final_df[final_df['IS_ERROR'] == True].copy()
    error_count = len(error_rows)
    
    # Hata nedenlerini belirle
    if not error_rows.empty:
        def get_error_reason(row):
            reasons = []
            if row['IS_INVALID_LENGTH']: reasons.append("KONTEYNER NO EKSİK VEYA FAZLA")
            if row['IS_CNTR_DUPLICATE']: reasons.append("TEKRAR EDEN KONTEYNER")
            if row['IS_MBL_DUPLICATE']: reasons.append("GİRDİDE TEKRAR EDEN MBL")
            return " + ".join(reasons)
        
        error_rows['HATA_NEDENI'] = error_rows.apply(get_error_reason, axis=1)
        final_skipped_df = pd.concat([final_skipped_df, error_rows], ignore_index=True).fillna('')

    # EXCEL ÇIKTISI OLUŞTURMA
    output_excel = io.BytesIO()
    with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
        df_export = final_df.drop(columns=['INPUT_ROW_ID', 'IS_CNTR_DUPLICATE', 'IS_MBL_DUPLICATE', 'IS_INVALID_LENGTH', 'CLEAN_CNTR', 'IS_ERROR'])
        df_export.to_excel(writer, index=False, sheet_name='Sheet1')
        workbook = writer.book
        worksheet = writer.sheets['Sheet1']
        
        format_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
        format_orange = workbook.add_format({'bg_color': '#FCE4D6', 'font_color': '#C65911'})
        
        for row_num in range(len(final_df)):
            if final_df['IS_INVALID_LENGTH'].iloc[row_num]:
                worksheet.set_row(row_num + 1, None, format_red)
            elif final_df['IS_CNTR_DUPLICATE'].iloc[row_num] or final_df['IS_MBL_DUPLICATE'].iloc[row_num]:
                worksheet.set_row(row_num + 1, None, format_orange)
    output_excel.seek(0)

    # SKIPPED EXCEL ÇIKTISI (Hatalar ve Düzeltilenler Sayfaları)
    skipped_bytes = None
    if not final_skipped_df.empty or st.session_state['correction_log']:
        skipped_buffer = io.BytesIO()
        with pd.ExcelWriter(skipped_buffer, engine='xlsxwriter') as writer:
            if not final_skipped_df.empty:
                df_skipped_export = final_skipped_df.drop(columns=['INPUT_ROW_ID', 'IS_CNTR_DUPLICATE', 'IS_MBL_DUPLICATE', 'IS_INVALID_LENGTH', 'CLEAN_CNTR', 'IS_ERROR'], errors='ignore')
                df_skipped_export.to_excel(writer, index=False, sheet_name='Hatalar')
                workbook = writer.book
                worksheet = writer.sheets['Hatalar']
                format_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
                format_orange = workbook.add_format({'bg_color': '#FCE4D6', 'font_color': '#C65911'})
                
                if 'HATA_NEDENI' in df_skipped_export.columns:
                    for row_num, reason in enumerate(df_skipped_export['HATA_NEDENI']):
                        reason_str = str(reason)
                        if "EKSİK VEYA FAZLA" in reason_str:
                            worksheet.set_row(row_num + 1, None, format_red)
                        elif "TEKRAR" in reason_str:
                            worksheet.set_row(row_num + 1, None, format_orange)
            
            # Düzeltilenler logunu ayrı sayfaya yaz
            if st.session_state['correction_log']:
                log_df = pd.DataFrame(st.session_state['correction_log'])
                log_df.to_excel(writer, index=False, sheet_name='Düzeltilenler')
                
        skipped_buffer.seek(0)
        skipped_bytes = skipped_buffer

    # TMAXX CSV ÇIKTILARI
    if "VOL" not in final_df.columns: final_df["VOL"] = ""
    tmaxx_files_dict = {}
    
    def get_tmaxx_err_suffix(row):
        errs = []
        if row.get('IS_CNTR_DUPLICATE', False): errs.append("CNTR TEKRAR")
        if row.get('IS_MBL_DUPLICATE', False): errs.append("MBL TEKRAR")
        if row.get('IS_INVALID_LENGTH', False): errs.append("UZUNLUK HATASI")
        return f" [HATA: {' + '.join(errs)}]" if errs else ""

    if 'KAYNAK_SAYFA' in final_df.columns:
        for sheet_name in final_df['KAYNAK_SAYFA'].unique():
            sheet_df = final_df[final_df['KAYNAK_SAYFA'] == sheet_name].copy()
            tmaxx_df = sheet_df[["CNTR NO", "VOL", "IS_CNTR_DUPLICATE", "IS_MBL_DUPLICATE", "IS_INVALID_LENGTH"]].copy()
            tmaxx_df['CNTR NO'] = tmaxx_df['CNTR NO'] + tmaxx_df.apply(get_tmaxx_err_suffix, axis=1)
            tmaxx_df = tmaxx_df[["CNTR NO", "VOL"]]
            tmaxx_df.columns = ['Container No', 'Container Type']
            tmaxx_df = tmaxx_df[tmaxx_df['Container No'] != '']
            
            if not tmaxx_df.empty:
                output_csv = tmaxx_df.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')
                safe_name = str(sheet_name).replace("/", "_").replace("\\", "_")
                tmaxx_files_dict[f"{safe_name}.csv"] = output_csv

    # Session State Güncellemeleri
    st.session_state['processed_data'] = final_df
    st.session_state['skipped_data'] = final_skipped_df
    st.session_state['excel_bytes'] = output_excel
    st.session_state['skipped_bytes'] = skipped_bytes
    st.session_state['tmaxx_files'] = tmaxx_files_dict
    st.session_state['report_stats'] = {
        'skipped': len(final_skipped_df),
        'duplicates_and_errors': error_count,
        'final': len(final_df)
    }

# ==========================================
# 2. ARAYÜZ (SIDEBAR VE ANA EKRAN)
# ==========================================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2821/2821854.png", width=100) 
    st.title("Kullanım Kılavuzu")
    st.markdown("""
    1. **Dosyaları Sürükleyin:** Excel dosyalarını atın.
    2. **Başlat:** Sistem taramaya başlar.
    3. **Hataları Düzelt:** Bulunan hataları *Düzeltme Paneli* sekmesinden anında onarın.
    4. **Sonuçlar:** - **Tam Liste:** Birleştirilmiş tüm liste.
        - **Tmaxx Listesi:** Her sayfa için ayrı yükleme listesi.
        - **Hata Listesi:** (Hatalar ve Düzeltme Geçmişi dahil)
    """)
    st.markdown("---")
    st.caption("v4.0 - İnteraktif Hata Düzeltme Paneli")


st.title("🚢 Lojistik Operasyon Asistanı")
st.markdown("Dağınık Excel dosyalarını birleştirir, eksik, mükerrer ve hatalı konteyner kayıtlarını kontrol eder. **Hataları anında ekranda düzeltmenizi sağlar.**")

# Session state ilk tanımlamalar
if 'raw_data' not in st.session_state: st.session_state['raw_data'] = None
if 'raw_skipped' not in st.session_state: st.session_state['raw_skipped'] = None
if 'correction_log' not in st.session_state: st.session_state['correction_log'] = []
if 'processed_data' not in st.session_state: st.session_state['processed_data'] = None

uploaded_files = st.file_uploader("📂 Excel Dosyalarını Buraya Bırakın", type=["xlsx", "xls"], accept_multiple_files=True)

if uploaded_files and st.session_state.get('last_uploaded_files') != uploaded_files:
    st.session_state['raw_data'] = None
    st.session_state['processed_data'] = None
    st.session_state['correction_log'] = []
    st.session_state['last_uploaded_files'] = uploaded_files

if uploaded_files:
    if st.session_state['raw_data'] is None:
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
                    st.session_state['raw_data'] = pd.concat(all_dfs, ignore_index=True).fillna('')
                    st.session_state['raw_skipped'] = pd.concat(all_skipped_dfs, ignore_index=True).fillna('') if all_skipped_dfs else pd.DataFrame()
                    st.session_state['correction_log'] = []
                    
                    run_evaluation_and_outputs()
                    
                    my_bar.empty()
                    st.balloons()
                    st.rerun()
                else:
                    st.error("❌ Dosyalar okunamadı veya veri bulunamadı.")


# ==========================================
# 3. SONUÇLAR VE DÜZELTME EKRANI
# ==========================================
if st.session_state['processed_data'] is not None:
    stats = st.session_state['report_stats']
    final_df = st.session_state['processed_data']
    suspicious_count = len(final_df[final_df['VOL'] == "⚠️ ŞÜPHELİ (KARIŞIK TİP)"]) if 'VOL' in final_df.columns else 0
    
    st.write("")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Konteyner", stats['final'], "✅ İşlenen")
    c2.metric("Mükerrer & Uzunluk Hatası", stats['duplicates_and_errors'], "🚨 Hata", delta_color="inverse" if stats['duplicates_and_errors'] > 0 else "normal")
    c3.metric("Toplam İptal Edilen Veri", len(st.session_state['raw_skipped']), "Eksik Bilgi")
    c4.metric("Düzeltilen Kayıt", len(st.session_state['correction_log']), "📝 Onarıldı" if len(st.session_state['correction_log']) > 0 else "Temiz", delta_color="normal")
    
    st.markdown("---")

    if stats['duplicates_and_errors'] > 0:
        st.error(f"🚨 DİKKAT: İşlenen verilerde {stats['duplicates_and_errors']} adet hatalı veya mükerrer kayıt bulundu! Aşağıdaki '🛠️ Düzeltme Paneli' sekmesinden düzeltebilirsiniz.")

    tab1, tab2, tab3, tab4 = st.tabs(["📊 Bilgi & Grafikler", "🛠️ Düzeltme Paneli", "📥 Çıktıları İndir", "👀 Tam Liste"])

    with tab1:
        if not final_df.empty:
            col_info, col_graph2 = st.columns([1.5, 2])
            with col_info:
                st.subheader("🎨 Excel Çıktıları Renk Kodları")
                st.info("İndireceğiniz **Excel dosyalarındaki** satırlar, içerdiği hata tipine göre otomatik renklendirilir:")
                st.markdown("""
                <div><span class="color-box red-box"></span> <b>Kırmızı:</b> Konteyner No Eksik veya Fazla (11 Hane Değil)</div>
                <div style="margin-top: 10px;"><span class="color-box orange-box"></span> <b>Turuncu:</b> Mükerrer (Tekrar Eden) Kayıt</div>
                <br>
                <small><em>* İpucu: Bir satırda hem mükerrer hem uzunluk hatası varsa, kırmızı renk (uzunluk hatası) öncelikli gösterilir.</em></small>
                """, unsafe_allow_html=True)
            with col_graph2:
                st.subheader("Konteyner Tipleri")
                plot_df = final_df.copy()
                plot_df['VOL'] = plot_df['VOL'].replace('', 'Belirsiz')
                fig_vol = px.bar(plot_df['VOL'].value_counts().reset_index(), x='VOL', y='count', title='Tip Dağılımı', labels={'count':'Adet', 'VOL':'Tip'})
                st.plotly_chart(fig_vol, key="chart2", use_container_width=True)

    with tab2:
        st.subheader("🛠️ Hatalı Kayıtları İnteraktif Olarak Düzeltin")
        error_df_view = final_df[final_df['IS_ERROR'] == True].copy()
        
        if not error_df_view.empty:
            st.info("Aşağıdaki tablodan **MB/L NO** veya **CNTR NO** değerlerini tıklayıp doğrudan değiştirebilirsiniz. Değişiklik yaptıktan sonra 'Güncelle ve Uygula' butonuna basın.")
            
            # Kullanıcıya göstereceğimiz kolonlar
            display_cols = ['INPUT_ROW_ID', 'KAYNAK_SAYFA', 'MB/L NO', 'CNTR NO', 'VOL']
            
            # Data Editor
            edited_df = st.data_editor(
                error_df_view[display_cols],
                key="error_editor",
                disabled=['INPUT_ROW_ID', 'KAYNAK_SAYFA', 'VOL'], # Bu kolonlar değiştirilemez
                use_container_width=True,
                hide_index=True
            )
            
            if st.button("✅ Değişiklikleri Güncelle ve Uygula", type="primary"):
                changes_made = False
                for idx in edited_df.index:
                    row_id = edited_df.loc[idx, 'INPUT_ROW_ID']
                    
                    old_mbl = error_df_view.loc[idx, 'MB/L NO']
                    new_mbl = edited_df.loc[idx, 'MB/L NO']
                    
                    old_cntr = error_df_view.loc[idx, 'CNTR NO']
                    new_cntr = edited_df.loc[idx, 'CNTR NO']
                    
                    # Eğer değer değişmişse logla ve ana veride güncelle
                    if str(old_mbl) != str(new_mbl) or str(old_cntr) != str(new_cntr):
                        st.session_state['correction_log'].append({
                            'KAYNAK_SAYFA': error_df_view.loc[idx, 'KAYNAK_SAYFA'],
                            'ESKI_MB/L NO': old_mbl,
                            'YENI_MB/L NO': new_mbl,
                            'ESKI_CNTR NO': old_cntr,
                            'YENI_CNTR NO': new_cntr,
                            'DURUM': 'Manuel Onarıldı'
                        })
                        
                        # raw_data'yı güncelle
                        mask = st.session_state['raw_data']['INPUT_ROW_ID'] == row_id
                        st.session_state['raw_data'].loc[mask, 'MB/L NO'] = str(new_mbl).strip().upper()
                        st.session_state['raw_data'].loc[mask, 'CNTR NO'] = str(new_cntr).strip().upper()
                        changes_made = True
                
                if changes_made:
                    st.success("Değişiklikler uygulandı! Listeler yeniden hesaplanıyor...")
                    run_evaluation_and_outputs()
                    st.rerun()
                else:
                    st.warning("Herhangi bir değişiklik yapmadınız.")
        else:
            st.success("🎉 Mükemmel! Şu anda düzeltilmesi gereken mükerrer veya uzunluk hatası içeren bir kayıt kalmadı.")

        # Düzeltme Geçmişini Göster
        if st.session_state['correction_log']:
            st.markdown("### 📝 Düzeltme Geçmişi")
            st.dataframe(pd.DataFrame(st.session_state['correction_log']), use_container_width=True)

    with tab3:
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
                st.download_button(label="⚠️ 3. Hatalı & Düzeltilmiş Kayıtlar", data=st.session_state['skipped_bytes'], file_name="HATALI_KAYITLAR.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.success("Hata yok! Harika! 🎉")

    with tab4:
        display_df = final_df.drop(columns=['INPUT_ROW_ID', 'IS_CNTR_DUPLICATE', 'IS_MBL_DUPLICATE', 'IS_INVALID_LENGTH', 'CLEAN_CNTR', 'IS_ERROR'])
        st.dataframe(display_df, use_container_width=True)
    
    st.markdown("---")
    if st.button("🔄 Yeni İşlem Başlat"):
        for key in st.session_state.keys(): del st.session_state[key]
        st.rerun()
