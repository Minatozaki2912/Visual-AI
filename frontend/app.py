import streamlit as st
import requests
import os
import time
import math
import base64
from PIL import Image, ImageStat 


# --- HÀM BỔ TRỢ: ĐÓNG KHUNG ẢNH CHUẨN E-COMMERCE ---
def get_image_html(img_path, fixed_height=250):
    """Ép chiều cao và TỰ ĐỘNG THÊM NỀN ĐEN cho các ảnh có chữ Trắng/Sáng"""
    if not os.path.exists(img_path):
        return "<div style='color:red; text-align:center; padding:50px;'>Lỗi ảnh</div>"

    ext = img_path.split(".")[-1].lower()
    mime_type = "image/png" if ext == "png" else "image/jpeg"
    
    # Mặc định không có nền CSS
    bg_css = "" 
    
    try:
        # Nếu là ảnh PNG, phân tích độ sáng xem có phải chữ Trắng không
        if ext == "png":
            img = Image.open(img_path)
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                img_rgba = img.convert("RGBA")
                alpha_mask = img_rgba.split()[3]
                stat = ImageStat.Stat(img_rgba.convert("L"), mask=alpha_mask)
                avg_brightness = stat.mean[0] if stat.mean else 128
                
                # Nếu hình in siêu sáng (Trắng) -> Bơm CSS nền Đen nhám
                if avg_brightness > 127:
                    bg_css = "background-color: #1a1a1a; border-radius: 6px; padding: 10px;"
    except Exception:
        pass # Bỏ qua nếu có lỗi đọc file, giữ nguyên không có nền

    with open(img_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")

    return f'<img src="data:{mime_type};base64,{data}" style="max-height: {fixed_height}px; max-width: 100%; object-fit: contain; {bg_css}">'


# --- 1. CẤU HÌNH TRANG ---
st.set_page_config(
    page_title="NEXUS | Visual Search",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "has_searched" not in st.session_state:
    st.session_state.has_searched = False

st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 1400px; }
    .top-navbar { display: flex; justify-content: space-between; align-items: center; padding: 15px 30px; border-bottom: 1px solid #e5e5e5; margin-bottom: 30px; background-color: white; }
    .brand-logo { font-size: 28px; font-weight: 900; letter-spacing: 4px; color: #000; }
    .nav-links { display: flex; gap: 30px; font-size: 14px; font-weight: 500; text-transform: uppercase; color: #333; }
    
    .product-card { 
        background: #fff; transition: 0.3s ease; margin-bottom: 20px; 
        border: 1px solid #eaeaea; border-radius: 8px; overflow: hidden;
    }
    .product-card:hover { transform: translateY(-5px); box-shadow: 0 10px 20px rgba(0,0,0,0.08); border-color: #ddd;}
    .product-img-box {
        height: 280px; display: flex; align-items: center; justify-content: center; 
        background-color: #fcfcfc; padding: 15px; border-bottom: 1px solid #f0f0f0;
    }
    .product-info { padding: 15px; text-align: center; }
    .product-brand { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 5px; font-weight: 600;}
    .product-name { font-size: 14px; color: #111; margin-bottom: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500;}
    </style>
    """,
    unsafe_allow_html=True,
)

tab_shop, tab_admin = st.tabs(["🛍️ CỬA HÀNG", "⚙️ QUẢN TRỊ KHO (ADMIN)"])

# ==========================================
# 🛒 GIAO DIỆN DÀNH CHO KHÁCH HÀNG (SHOP)
# ==========================================
with tab_shop:
    st.markdown(
        """
        <div class="top-navbar">
            <div class="nav-links"><span>WOMEN</span><span>MEN</span><span>KIDS</span></div>
            <div class="brand-logo">NEXUS FASHION</div>
            <div class="nav-links"><span>🔍 VISUAL SEARCH</span><span>LOGIN</span><span>CART (0)</span></div>
        </div>
    """,
        unsafe_allow_html=True,
    )

    with st.expander("📸 TÌM KIẾM SẢN PHẨM QUA HÌNH IN / STICKER", expanded=True):
        col_upload, col_btn = st.columns([3, 1])
        with col_upload:
            uploaded_file = st.file_uploader(
                "Tải lên hình in/logo bạn muốn tìm kiếm",
                type=["jpg", "png", "jpeg"],
                label_visibility="collapsed",
            )
        with col_btn:
            st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
            search_btn = st.button(
                "TÌM KIẾM NGAY", type="primary", use_container_width=True
            )

    if search_btn and uploaded_file:
        with st.spinner("AI đang quét toàn bộ kho sản phẩm..."):
            try:
                res = requests.post(
                    "http://127.0.0.1:8000/search-image",
                    files={"file": uploaded_file.getvalue()},
                )
                if res.status_code == 200:
                    st.session_state.search_results = res.json().get("results", [])
                    st.session_state.has_searched = True
                else:
                    st.error(f"Lỗi từ Backend: {res.text}")
            except Exception as e:
                st.error("Không thể kết nối Backend.")

    if st.session_state.has_searched:
        st.markdown(
            "<hr style='margin: 30px 0; border: none; border-top: 1px solid #eee;'>",
            unsafe_allow_html=True,
        )
        results = st.session_state.search_results

        if not results:
            st.info("Không tìm thấy sản phẩm nào có hình in khớp với yêu cầu của bạn.")
        else:
            st.markdown(
                f"<h3 style='text-align: center; font-weight: 300; letter-spacing: 2px; margin-bottom: 20px;'>TÌM THẤY {len(results)} SẢN PHẨM PHÙ HỢP</h3>",
                unsafe_allow_html=True,
            )

            ITEMS_PER_PAGE_SHOP = 8  
            total_pages_shop = math.ceil(len(results) / ITEMS_PER_PAGE_SHOP)

            if total_pages_shop > 1:
                col_sp1, col_sp2, col_sp3 = st.columns([1, 2, 1])
                with col_sp2:
                    current_page_shop = st.number_input(
                        "Trang số:",
                        min_value=1,
                        max_value=total_pages_shop,
                        value=1,
                        step=1,
                        key="shop_pagination",
                    )
            else:
                current_page_shop = 1

            start_idx = (current_page_shop - 1) * ITEMS_PER_PAGE_SHOP
            end_idx = start_idx + ITEMS_PER_PAGE_SHOP
            display_results = results[start_idx:end_idx]

            cols_per_row = 4
            for i in range(0, len(display_results), cols_per_row):
                cols = st.columns(cols_per_row, gap="large")
                for j in range(cols_per_row):
                    if i + j < len(display_results):
                        item = display_results[i + j]
                        file_name = item["file_name"]
                        img_path = os.path.join("../data/images", file_name)

                        with cols[j]:
                            img_html = get_image_html(img_path, fixed_height=250)

                            st.markdown(
                                f"""
                                <div class='product-card'>
                                    <div class='product-img-box'>
                                        {img_html}
                                    </div>
                                    <div class='product-info'>
                                        <div class='product-brand'>NEXUS EXCLUSIVE</div>
                                        <div class='product-name' title='{file_name}'>{file_name.replace('.jpg', '').replace('.png', '').replace('_', ' ').title()}</div>
                                    </div>
                                </div>
                            """,
                                unsafe_allow_html=True,
                            )

                            st.button(
                                "XEM CHI TIẾT",
                                key=f"btn_shop_{file_name}_{i}_{j}",
                                use_container_width=True,
                            )

# ==========================================
# ⚙️ GIAO DIỆN DÀNH CHO ADMIN QUẢN TRỊ
# ==========================================
with tab_admin:
    st.markdown("### 📦 BẢNG ĐIỀU KHIỂN KHO HÀNG")

    st.markdown("#### ➕ Thêm Sản Phẩm Mới")
    new_product_file = st.file_uploader(
        "Kéo thả ảnh sản phẩm mới vào đây",
        type=["jpg", "png", "jpeg"],
        key="upload_new",
    )
    if st.button("Tự động quét AI & Đưa vào kho", type="primary"):
        if new_product_file:
            with st.spinner("AI đang cắt lớp và đồng bộ Vector..."):
                files = {"file": (new_product_file.name, new_product_file.getvalue())}
                res = requests.post("http://127.0.0.1:8000/add-product", files=files)
                if res.status_code == 200:
                    response_data = res.json()
                    msg = response_data.get("message")
                    time_taken = response_data.get("time_taken", 0)
                    
                    st.success(f"{msg} (⏱️ Mất {time_taken} giây)")
                    
                    time.sleep(1.5) 
                    st.rerun()
                else:
                    st.error(f"Lỗi đồng bộ: {res.text}")
        else:
            st.warning("Vui lòng tải ảnh lên trước!")

    st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)

    st.markdown("#### 🖼️ Danh Mục Sản Phẩm Đang Bán")
    try:
        res_list = requests.get("http://127.0.0.1:8000/list-products")
        if res_list.status_code == 200:
            products = res_list.json().get("products", [])

            if not products:
                st.info("Kho hàng hiện đang trống.")
            else:
                ITEMS_PER_PAGE_ADMIN = 10
                total_pages_admin = math.ceil(len(products) / ITEMS_PER_PAGE_ADMIN)

                col_p1, col_p2, col_p3 = st.columns([1, 2, 1])
                with col_p2:
                    current_page_admin = st.number_input(
                        "Chuyển đến trang:",
                        min_value=1,
                        max_value=total_pages_admin,
                        value=1,
                        step=1,
                        key="admin_pagination",
                    )

                start_idx_ad = (current_page_admin - 1) * ITEMS_PER_PAGE_ADMIN
                end_idx_ad = start_idx_ad + ITEMS_PER_PAGE_ADMIN
                display_products = products[start_idx_ad:end_idx_ad]

                st.markdown(
                    f"<p style='text-align: center; color: #666;'>Đang hiển thị trang {current_page_admin} / {total_pages_admin} (Tổng {len(products)} sản phẩm)</p>",
                    unsafe_allow_html=True,
                )
                st.markdown("<br>", unsafe_allow_html=True)

                cols_per_row = 5
                for i in range(0, len(display_products), cols_per_row):
                    cols = st.columns(cols_per_row, gap="medium")
                    for j in range(cols_per_row):
                        if i + j < len(display_products):
                            file_name = display_products[i + j]
                            img_path = os.path.join("../data/images", file_name)

                            with cols[j]:
                                img_html = get_image_html(img_path, fixed_height=180)

                                st.markdown(
                                    f"""
                                    <div style='height: 220px; display: flex; align-items: center; justify-content: center; background-color: #f8f9fa; border: 1px solid #eee; border-radius: 8px; padding: 10px;'>
                                        {img_html}
                                    </div>
                                    <p style='font-size: 12px; color: #555; text-align: center; margin: 10px 0 5px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;' title='{file_name}'>
                                        {file_name}
                                    </p>
                                """,
                                    unsafe_allow_html=True,
                                )

                                if st.button(
                                    "❌ Xóa",
                                    key=f"del_{file_name}",
                                    use_container_width=True,
                                ):
                                    with st.spinner("Đang dọn dẹp..."):
                                        res_del = requests.delete(
                                            f"http://127.0.0.1:8000/delete-product/{file_name}"
                                        )
                                        if res_del.status_code == 200:
                                            st.toast(f"Đã xóa {file_name}!")
                                            time.sleep(0.5)
                                            st.rerun()
    except Exception as e:
        st.error("Chưa kết nối được với Server Backend. Đảm bảo Uvicorn đang chạy.")