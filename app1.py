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
    [data-testid="stFileUploader"] section:hover { background-color: rgba(255, 255, 255, 0.06) !important; border-color: #4da6ff !important; box-shadow: 0px 0px 15px rgba(77, 166, 255, 0.15) !important; }
    .color-box { display: inline-block; width: 15px; height: 15px; border-radius: 3px; margin-right: 8px; vertical-align: middle; }
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
        if not col_str or col_str.lower() in ['nan', 'none', '']: col_str = "Unknown_Col"
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
        if 9 <= len(clean_m) <= 12: valid_containers.append(clean_m)
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
        if row.astype(str).str.strip().replace(['NAN', 'NONE', ''], pd.NA).isna().all(): continue
        input_row_id = str(uuid.uuid4()) 
        
        mbl_val = ""
        if mbl_col_name:
            raw_mbl = str(row[mbl_col_name]).upper().strip()
            if raw_mbl not in ['NAN', 'NONE', '', 'NA', 'UNKNOWN_COL']: mbl_val = clean_mbl_column(raw_mbl)
        
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
                    "INPUT_ROW_ID": input_row_id, "MB/L NO": mbl_val, "CNTR NO": cntr,
                    "VOL": ctype if ctype else "Unknown", "TEU": teu_val, "V/V": vessel_val
                }
                for col in ["POL", "POD", "BOOKING NO"]:
                     actual_col = next((c for c in df.columns if col in str(c).upper()), None)
                     if actual_col: row_data[col] = str(row[actual_col])
                new_rows.append(row_data)
        else:
            row_dict = row.to_dict()
            if not mbl_val and not containers: row_dict['HATA_NEDENI'] = "MBL VE KONTEYNER NO BULUNAMADI"
            elif not mbl_val: row_dict['HATA_NEDENI'] = "EKSİK MBL NO"
            else: row_dict['HATA_NEDENI'] = "EKSİK KONTEYNER NO"
            
            row_dict['BULUNAN_MBL'] = mbl_val if mbl_val else "YOK"
            row_dict['BULUNAN_CNTR'] = ", ".join(containers) if containers else "YOK"
            skipped_rows.append(row_dict)

    return pd.DataFrame(new_rows), pd.DataFrame(skipped_rows)


def evaluate_data(df):
    """Veriyi değerlendirir, hata durumlarını günceller."""
    eval_df = df.copy()
    eval_df['IS_CNTR_DUPLICATE'] = eval_df.duplicated(subset=['CNTR NO'], keep=False)
    mbl_row_counts = eval_df.groupby('MB/L NO')['INPUT_ROW_ID'].nunique()
    duplicate_mbls = mbl_row_counts[mbl_row_counts > 1].index
    eval_df['IS_MBL_DUPLICATE'] = eval_df['MB/L NO'].isin(duplicate_mbls)
    
    eval_df['CLEAN_CNTR'] = eval_df['CNTR NO'].astype(str).str.replace(r'\s+', '', regex=True)
    eval_df['IS_INVALID_LENGTH'] = eval_df['CLEAN_CNTR'].str.len() != 11
    eval_df['IS_ERROR'] = eval_df['IS_CNTR_DUPLICATE'] | eval_df['IS_MBL_DUPLICATE'] | eval_df['IS_INVALID_LENGTH']
    return eval_df

def generate_outputs():
    """Hata onarımı bittikten sonra en güncel veriyle Tmaxx ve Excel çıktılarını üretir."""
    final_df = evaluate_data(st.session_state['raw_data'])
    final_skipped_df = st.session_state['raw_skipped'].copy()
    
    error_rows = final_df[final_df['IS_ERROR'] == True].copy()
    
    if not error_rows.empty:
        def get_error_reason(row):
            reasons = []
            if row['IS_INVALID_LENGTH']: reasons.append("KONTEYNER NO EKSİK VEYA FAZLA")
            if row['IS_CNTR_DUPLICATE']: reasons.append("TEKRAR EDEN KONTEYNER")
            if row['IS_MBL_DUPLICATE']: reasons.append("GİRDİDE TEKRAR EDEN MBL")
            return " + ".join(reasons)
        error_rows['HATA_NEDENI'] = error_rows.apply(get_error_reason, axis=1)
        final_skipped_df = pd.concat([final_skipped_df, error_rows], ignore_index=True).fillna('')

    # 1. Ana Excel Çıktısı
    output_excel = io.BytesIO()
    with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
        df_export = final_df.drop(columns=['INPUT_ROW_ID', 'IS_CNTR_DUPLICATE', 'IS_MBL_DUPLICATE', 'IS_INVALID_LENGTH', 'CLEAN_CNTR', 'IS_ERROR'])
        df_export.to_excel(writer, index=False, sheet_name='Sheet1')
        workbook = writer.book
        worksheet = writer.sheets['Sheet1']
        
        format_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
        format_orange = workbook.add_format({'bg_color': '#FCE4D6', 'font_color': '#C65911'})
        
        for row_num in range(len(final_df)):
            if final_df['IS_INVALID_LENGTH'].iloc[row_num]: worksheet.set_row(row_num + 1, None, format_red)
            elif final_df['IS_CNTR_DUPLICATE'].iloc[row_num] or final_df['IS_MBL_DUPLICATE'].iloc[row_num]: worksheet.set_row(row_num + 1, None, format_orange)
    output_excel.seek(0)

    # 2. Hatalar ve Onarımlar (Skipped) Excel'i
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
                        if "EKSİK VEYA FAZLA" in reason_str: worksheet.set_row(row_num + 1, None, format_red)
                        elif "TEKRAR" in reason_str: worksheet.set_row(row_num + 1, None, format_orange)
            
            if st.session_state['correction_log']:
                pd.DataFrame(st.session_state['correction_log']).to_excel(writer, index=False, sheet_name='Düzeltilen_Loglar')
                
        skipped_buffer.seek(0)
        skipped_bytes = skipped_buffer

    # 3. TMAXX Dosyaları OLUŞTURMA (Düzeltilmiş Doğru Veriyle)
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
            # Kalan hatalar varsa tmaxx'a not düş
            tmaxx_df['CNTR NO'] = tmaxx_df['CNTR NO'] + tmaxx_df.apply(get_tmaxx_err_suffix, axis=1)
            tmaxx_df = tmaxx_df[["CNTR NO", "VOL"]]
            tmaxx_df.columns = ['Container No', 'Container Type']
            tmaxx_df = tmaxx_df[tmaxx_df['Container No'] != '']
            
            if not tmaxx_df.empty:
                output_csv = tmaxx_df.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')
                safe_name = str(sheet_name).replace("/", "_").replace("\\", "_")
                tmaxx_files_dict[f"{safe_name}.csv"] = output_csv

    st.session_state['processed_data'] = final_df
    st.session_state['excel_bytes'] = output_excel
    st.session_state['skipped_bytes'] = skipped_bytes
    st.session_state['tmaxx_files'] = tmaxx_files_dict
    st.session_state['report_stats'] = {
        'skipped': len(final_skipped_df),
        'duplicates_and_errors': len(error_rows),
        'final': len(final_df)
    }

# ==========================================
# 2. SESSION STATE & SIDEBAR
# ==========================================
if 'app_phase' not in st.session_state: st.session_state['app_phase'] = "upload" # 'upload', 'correction', 'results'
if 'raw_data' not in st.session_state: st.session_state['raw_data'] = None
if 'raw_skipped' not in st.session_state: st.session_state['raw_skipped'] = None
if 'correction_log' not in st.session_state: st.session_state['correction_log'] = []

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2821/2821854.png", width=100) 
    st.title("Lojistik Asistanı")
    st.markdown("""
    **İş Akışı:**
    1. 📥 Dosyaları Yükle
    2. 🔍 Analiz ve Kontrol
    3. 🛠️ **(Gerekirse)** Hataları Onar
    4. 📤 Doğrulanmış Çıktıları Al
    """)
    if st.session_state['app_phase'] != "upload":
        if st.button("🔄 Yeni İşlem Başlat", type="secondary"):
            for key in ['app_phase', 'raw_data', 'raw_skipped', 'correction_log', 'processed_data', 'last_uploaded_files']:
                if key in st.session_state: del st.session_state[key]
            st.rerun()

st.title("🚢 Lojistik Operasyon Asistanı")
st.markdown("Eksik, mükerrer ve hatalı konteyner kayıtlarını kontrol eder. Çıktıları üretmeden önce onarım şansı tanır.")

# ==========================================
# AŞAMA 1: DOSYA YÜKLEME VE ANALİZ
# ==========================================
if st.session_state['app_phase'] == "upload":
    uploaded_files = st.file_uploader("📂 Excel Dosyalarını Bırakın", type=["xlsx", "xls"], accept_multiple_files=True)
    if uploaded_files:
        if st.button("🚀 Analizi Başlat", type="primary"): 
            with st.spinner("Dosyalar okunuyor..."):
                all_dfs, all_skipped_dfs = [], []
                for i, uploaded_file in enumerate(uploaded_files):
                    try:
                        xls = pd.read_excel(uploaded_file, sheet_name=None, header=None, dtype=str)
                        for sheet_name, raw_df in xls.items():
                            df = find_and_set_header(raw_df)
                            if df is not None:
                                p_df, s_df = process_smart_rows(df)
                                if not p_df.empty:
                                    p_df['KAYNAK_DOSYA'], p_df['KAYNAK_SAYFA'] = uploaded_file.name, sheet_name
                                    all_dfs.append(p_df)
                                if not s_df.empty:
                                    s_df['KAYNAK_DOSYA'], s_df['KAYNAK_SAYFA'] = uploaded_file.name, sheet_name
                                    all_skipped_dfs.append(s_df)
                    except Exception as e:
                        st.error(f"Hata: {e}")
                
                if all_dfs:
                    st.session_state['raw_data'] = pd.concat(all_dfs, ignore_index=True).fillna('')
                    st.session_state['raw_skipped'] = pd.concat(all_skipped_dfs, ignore_index=True).fillna('') if all_skipped_dfs else pd.DataFrame()
                    st.session_state['correction_log'] = []
                    
                    # Veriyi değerlendirip hata var mı kontrol et
                    eval_data = evaluate_data(st.session_state['raw_data'])
                    error_count = eval_data['IS_ERROR'].sum()
                    
                    if error_count > 0:
                        st.session_state['app_phase'] = "correction" # Hataya takıldı, düzeltme aşamasına geç
                    else:
                        generate_outputs() # Hata yok, direkt çıktıları hazırla
                        st.session_state['app_phase'] = "results"
                    st.rerun()
                else:
                    st.error("❌ Veri bulunamadı.")

# ==========================================
# AŞAMA 2: DÜZELTME PANELİ (Sadece Hata Varsa Çalışır)
# ==========================================
elif st.session_state['app_phase'] == "correction":
    eval_data = evaluate_data(st.session_state['raw_data'])
    error_df_view = eval_data[eval_data['IS_ERROR'] == True].copy()
    
    st.error(f"🚨 Analiz sonucunda {len(error_df_view)} adet hatalı (Mükerrer veya Hatalı Uzunluk) kayıt bulundu. Çıktılar (Tmaxx, Excel) henüz oluşturulmadı.")
    st.info("💡 **Aşağıdaki tablodan hataları doğrudan düzeltebilirsiniz.** Düzeltmeleri yaptıktan sonra 'Onayla ve Çıktıları Hazırla' butonuna bastığınızda, sistem **düzelttiğiniz verileri baz alarak** nihai Tmaxx ve Excel dosyalarınızı üretecektir.")

    display_cols = ['INPUT_ROW_ID', 'KAYNAK_SAYFA', 'MB/L NO', 'CNTR NO', 'VOL']
    
    edited_df = st.data_editor(
        error_df_view[display_cols],
        key="error_editor",
        disabled=['INPUT_ROW_ID', 'KAYNAK_SAYFA', 'VOL'],
        use_container_width=True,
        hide_index=True
    )
    
    if st.button("✅ Onayla ve Çıktıları Hazırla (İlerle)", type="primary"):
        for idx in edited_df.index:
            row_id = edited_df.loc[idx, 'INPUT_ROW_ID']
            old_mbl, new_mbl = error_df_view.loc[idx, 'MB/L NO'], edited_df.loc[idx, 'MB/L NO']
            old_cntr, new_cntr = error_df_view.loc[idx, 'CNTR NO'], edited_df.loc[idx, 'CNTR NO']
            
            # Değişiklik varsa loga yaz ve ana veride güncelle
            if str(old_mbl) != str(new_mbl) or str(old_cntr) != str(new_cntr):
                st.session_state['correction_log'].append({
                    'KAYNAK_SAYFA': error_df_view.loc[idx, 'KAYNAK_SAYFA'],
                    'ESKI MB/L NO': old_mbl, 'YENI MB/L NO': new_mbl,
                    'ESKI CNTR NO': old_cntr, 'YENI CNTR NO': new_cntr
                })
                mask = st.session_state['raw_data']['INPUT_ROW_ID'] == row_id
                st.session_state['raw_data'].loc[mask, 'MB/L NO'] = str(new_mbl).strip().upper()
                st.session_state['raw_data'].loc[mask, 'CNTR NO'] = str(new_cntr).strip().upper()
        
        with st.spinner("Tmaxx ve Excel Çıktıları düzeltilmiş verilerle hazırlanıyor..."):
            generate_outputs()
            st.session_state['app_phase'] = "results"
            st.rerun()

# ==========================================
# AŞAMA 3: SONUÇLAR VE İNDİRME EKRANI
# ==========================================
elif st.session_state['app_phase'] == "results":
    stats = st.session_state['report_stats']
    final_df = st.session_state['processed_data']
    
    st.success("🎉 Dosyalarınız yüklendi, analiz edildi ve çıktılar başarıyla hazırlandı!")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam İşlenen", stats['final'], "✅ Onaylı")
    c2.metric("Kalan Uyarı/Hatalar", stats['duplicates_and_errors'], "⚠️ Dikkat", delta_color="inverse" if stats['duplicates_and_errors'] > 0 else "normal")
    c3.metric("Manuel Düzeltilenler", len(st.session_state['correction_log']), "📝 Onarıldı" if len(st.session_state['correction_log'])>0 else "")
    c4.metric("Eksik Veri (İptal)", stats['skipped'], "Listeye alınmadı")
    
    st.markdown("---")

    tab_download, tab_log, tab_list = st.tabs(["📥 Çıktıları İndir", "📝 Düzeltme Geçmişi (Neler Değişti?)", "👀 Tam Liste ve Grafikler"])

    with tab_download:
        st.subheader("Doğrulanmış Çıktı Dosyalarınız")
        st.info("Bu dosyalar, eğer onarım yaptıysanız, sizin **düzeltmeleriniz baz alınarak (doğru değerlerle)** oluşturulmuştur.")
        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1:
            st.download_button("📥 1. Temiz Liste (Excel)", data=st.session_state['excel_bytes'], file_name="BIRLESTIRILMIS_LISTE.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with col_d2:
            st.markdown("##### 📤 2. Tmaxx Dosyaları (CSV)")
            for file_name, file_bytes in st.session_state['tmaxx_files'].items():
                st.download_button(label=f"📥 {file_name}", data=file_bytes, file_name=file_name, mime="text/csv", key=f"dl_btn_{file_name}")
        with col_d3:
            if st.session_state['skipped_bytes']:
                st.download_button("⚠️ 3. Hata & Onarım Logları (Excel)", data=st.session_state['skipped_bytes'], file_name="HATALI_KAYITLAR.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_log:
        st.subheader("Değişiklik Kayıtları")
        if st.session_state['correction_log']:
            st.success("Çıktılar üretilmeden önce ekranda yaptığınız onarımlar aşağıda listelenmiştir. Bu bilgiler ayrıca 'Hata Logları' Excel dosyasına da eklenmiştir.")
            st.dataframe(pd.DataFrame(st.session_state['correction_log']), use_container_width=True)
        else:
            st.info("Herhangi bir manuel düzeltme işlemi yapılmadı.")

    with tab_list:
        display_df = final_df.drop(columns=['INPUT_ROW_ID', 'IS_CNTR_DUPLICATE', 'IS_MBL_DUPLICATE', 'IS_INVALID_LENGTH', 'CLEAN_CNTR', 'IS_ERROR'])
        col_t, col_g = st.columns([2, 1])
        with col_t:
             st.dataframe(display_df, use_container_width=True, height=400)
        with col_g:
             plot_df = final_df.copy()
             plot_df['VOL'] = plot_df['VOL'].replace('', 'Belirsiz')
             st.plotly_chart(px.bar(plot_df['VOL'].value_counts().reset_index(), x='VOL', y='count', title='Tip Dağılımı'), use_container_width=True)
