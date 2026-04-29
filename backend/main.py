import io
import os
import uuid
import shutil
import time
from glob import glob
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageStat, ImageEnhance, ImageOps, ImageFilter
from sentence_transformers import SentenceTransformer
from ultralytics import YOLO
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)
from contextlib import asynccontextmanager

# ==========================================
# CẤU HÌNH HỆ THỐNG
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
IMAGE_DIR = "../data/images"
DB_PATH = "../vector_db_data"
COLLECTION_NAME = "sticker_visual_search"

CLIP_MODEL_NAME = "clip-ViT-B-32"
YOLO_MODEL_NAME = "yolov8s.pt"

client = QdrantClient(path=DB_PATH)
model = None
detector = None


# ==========================================
# HÀM BỔ TRỢ & TIỀN XỬ LÝ
# ==========================================
def setup_system():
    global model, detector
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)

    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=512, distance=Distance.COSINE),
        )
        print("=> Đã tạo Database Qdrant thành công.")

    model = SentenceTransformer(CLIP_MODEL_NAME)

    yolo_path = os.path.join(MODELS_DIR, YOLO_MODEL_NAME)
    if not os.path.exists(yolo_path):
        print(f"=> Đang tự động tải {YOLO_MODEL_NAME}...")
        YOLO(YOLO_MODEL_NAME)
        if os.path.exists(YOLO_MODEL_NAME):
            shutil.move(YOLO_MODEL_NAME, yolo_path)
    detector = YOLO(yolo_path)
    print("=> Toàn bộ AI Models đã sẵn sàng!")


def load_and_preprocess_image(image_source):
    """
    Xử lý ảnh PNG thông minh:
    Tự động lót nền Đen Tuyệt Đối cho chữ Trắng, và Trắng Tuyệt Đối cho chữ Đen
    nhằm giữ lại tối đa đặc trưng hình học (Geometry) của nét chữ.
    """
    img = Image.open(image_source)

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        alpha_mask = img.split()[3]

        stat = ImageStat.Stat(img.convert("L"), mask=alpha_mask)
        avg_brightness = stat.mean[0] if stat.mean else 128

        # THUẬT TOÁN TƯƠNG PHẢN TUYỆT ĐỐI
        if avg_brightness > 127:
            bg_color = (0, 0, 0, 255)
        else:
            bg_color = (255, 255, 255, 255)

        background = Image.new("RGBA", img.size, bg_color)
        background.paste(img, mask=alpha_mask)
        return background.convert("RGB")

    return img.convert("RGB")


def get_crops(img, detector, conf=0.15, padding=15):
    """Sử dụng YOLO để gắp vật thể và nới lỏng viền (Padding) để không lẹm chữ"""
    crops = []
    w, h = img.size
    results = detector(img, conf=conf, verbose=False)
    for box in results[0].boxes.xyxy:
        x1, y1, x2, y2 = map(int, box)
        if x2 > x1 and y2 > y1:
            # Thuật toán nới lỏng viền (Smart Padding)
            px1 = max(0, x1 - padding)
            py1 = max(0, y1 - padding)
            px2 = min(w, x2 + padding)
            py2 = min(h, y2 + padding)
            crops.append(img.crop((px1, py1, px2, py2)))
    return crops


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_system()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ==========================================
# API ENDPOINTS
# ==========================================
@app.post("/search-image")
async def search_by_sticker(file: UploadFile = File(...)):
    FIXED_THRESHOLD = 0.50
    try:
        content = await file.read()
        query_img = load_and_preprocess_image(io.BytesIO(content))
        w, h = query_img.size
        total_area = w * h

        # ---------------------------------------------------------
        # 1. QUÉT YOLO ĐỂ TÌM VẬT THỂ (Móc khóa, Sticker...)
        # Nới lỏng viền (padding=15) để không lẹm chữ
        # ---------------------------------------------------------
        raw_crops = get_crops(query_img, detector, conf=0.15, padding=15)

        valid_crops = []
        for crop in raw_crops:
            cw, ch = crop.size
            crop_area = cw * ch
            # Lọc rác vụn (<5%) nhưng mở trần lên 99% để không bỏ sót ảnh cận cảnh
            if 0.05 * total_area < crop_area < 0.99 * total_area:
                valid_crops.append(crop)

        # ---------------------------------------------------------
        # 2. LUẬT ƯU TIÊN TUYỆT ĐỐI (Chống nhiễu bối cảnh/cánh tay)
        # ---------------------------------------------------------
        search_targets = []
        if len(valid_crops) > 0:
            # Nếu YOLO gắp được vật thể -> VỨT BỎ ảnh gốc chứa tay/bàn
            search_targets = valid_crops
        else:
            # Nếu YOLO mù hoàn toàn -> Kích hoạt Multi-Scale Fallback (Bảo hiểm 3 tầng)
            search_targets.append(query_img)  # Bản 1: Giữ nguyên 100%

            # Bản 2: Cắt hờ 15% viền (Loại bỏ ngón tay cầm ở mép)
            pad_15x, pad_15y = int(w * 0.15), int(h * 0.15)
            if w > pad_15x * 2 and h > pad_15y * 2:
                search_targets.append(
                    query_img.crop((pad_15x, pad_15y, w - pad_15x, h - pad_15y))
                )

            # Bản 3: Cắt sâu 25% (Focus cực mạnh vào lõi thiết kế, loại bỏ móc sắt)
            pad_25x, pad_25y = int(w * 0.25), int(h * 0.25)
            if w > pad_25x * 2 and h > pad_25y * 2:
                search_targets.append(
                    query_img.crop((pad_25x, pad_25y, w - pad_25x, h - pad_25y))
                )

        # ---------------------------------------------------------
        # 3. TTA & ENHANCEMENT (Làm nét, Xoay góc & KHỬ CHÓI SÁNG)
        # ---------------------------------------------------------
        augmented_targets = []
        for crop in search_targets:
            # Phiên bản 1: Tiêu chuẩn (Tăng nét, Tương phản) - Tốt cho ảnh mờ
            sharp_enhancer = ImageEnhance.Sharpness(crop)
            crop_sharp = sharp_enhancer.enhance(2.0)
            contrast_enhancer = ImageEnhance.Contrast(crop_sharp)
            crop_std = contrast_enhancer.enhance(1.2)

            # Phiên bản 2: Cứu sáng (Glare Rescue) - Tốt cho vật liệu bóng/acrylic
            # Thuật toán Autocontrast ép các mảng lóa trắng phải lộ ra chi tiết ẩn
            crop_rescue = ImageOps.autocontrast(crop, cutoff=2)

            # Quét các góc độ cho cả 2 phiên bản
            angles = [0, 90, 180, 270, 15, -15]
            for angle in angles:
                if angle == 0:
                    augmented_targets.append(crop_std)
                    augmented_targets.append(crop_rescue)
                else:
                    # fillcolor=Trắng để phần viền mở rộng khi xoay xéo không bị đen (tránh ảo giác)
                    augmented_targets.append(
                        crop_std.rotate(angle, expand=True, fillcolor=(255, 255, 255))
                    )
                    augmented_targets.append(
                        crop_rescue.rotate(
                            angle, expand=True, fillcolor=(255, 255, 255)
                        )
                    )

        # ---------------------------------------------------------
        # 4. TRUY VẤN DATABASE & LỌC KẾT QUẢ TỐT NHẤT
        # ---------------------------------------------------------
        unique_results = {}
        for crop in augmented_targets:
            query_vector = model.encode(crop, show_progress_bar=False).tolist()
            response = client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                limit=50,
                score_threshold=FIXED_THRESHOLD,
            )

            for p in response.points:
                fname = p.payload.get("file_name")
                score = round(p.score, 4)
                # Chỉ lấy điểm Cosine Similarity cao nhất nếu có nhiều mẩu cùng trúng 1 sticker
                if fname not in unique_results or score > unique_results[fname]:
                    unique_results[fname] = score

        # Sắp xếp từ cao xuống thấp và cắt Top 24
        final_list = [{"score": s, "file_name": f} for f, s in unique_results.items()]
        sorted_results = sorted(final_list, key=lambda x: x["score"], reverse=True)

        return {"results": sorted_results[:24]}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/list-products")
async def list_products():
    image_paths = glob(os.path.join(IMAGE_DIR, "*.[jJ][pP][gG]")) + glob(
        os.path.join(IMAGE_DIR, "*.[pP][nN][gG]")
    )
    return {"products": [os.path.basename(p) for p in image_paths]}


@app.post("/add-product")
async def add_product(file: UploadFile = File(...)):
    try:
        start_time = time.time()

        file_name = file.filename
        file_path = os.path.join(IMAGE_DIR, file_name)
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        full_img = load_and_preprocess_image(file_path)

        # Output trong kho là ảnh sticker tĩnh sạch sẽ, chỉ cần 1 Vector duy nhất
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, file_name + "_full")),
                vector=model.encode(full_img, show_progress_bar=False).tolist(),
                payload={"file_name": file_name, "is_crop": False},
            )
        ]

        client.upsert(collection_name=COLLECTION_NAME, points=points)

        end_time = time.time()
        process_time = round(end_time - start_time, 2)

        return {
            "message": f"Đã lưu file thiết kế Sticker {file_name} thành công!",
            "time_taken": process_time,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete-product/{file_name}")
async def delete_product(file_name: str):
    try:
        file_path = os.path.join(IMAGE_DIR, file_name)
        if os.path.exists(file_path):
            os.remove(file_path)

        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(key="file_name", match=MatchValue(value=file_name))
                ]
            ),
        )
        return {"message": f"Đã xóa sticker {file_name} khỏi hệ thống!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
