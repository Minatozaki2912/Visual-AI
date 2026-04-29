import os
import time
import uuid
import logging
from glob import glob
from PIL import Image, ImageStat
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Static-Sticker-Indexer")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
IMAGE_DIR = "../data/images"
DB_PATH = "../vector_db_data"
COLLECTION_NAME = "sticker_visual_search"

CLIP_MODEL_NAME = "clip-ViT-B-32"
BATCH_SIZE = 50


def load_and_preprocess_image(image_source):
    """
    Xử lý ảnh PNG thông minh: 
    Tự động lót nền Đen Tuyệt Đối cho chữ Trắng, và Trắng Tuyệt Đối cho chữ Đen
    nhằm giữ lại tối đa đặc trưng hình học (Geometry) của nét chữ.
    """
    img = Image.open(image_source)
    
    # Kiểm tra xem ảnh có kênh Alpha (nền trong suốt) hay không
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        img = img.convert("RGBA")
        alpha_mask = img.split()[3]
        
        # Đo độ sáng trung bình của phần hình in (bỏ qua phần trong suốt)
        stat = ImageStat.Stat(img.convert("L"), mask=alpha_mask)
        avg_brightness = stat.mean[0] if stat.mean else 128
        
        # THUẬT TOÁN TƯƠNG PHẢN TUYỆT ĐỐI
        if avg_brightness > 127:
            # Hình in sáng (Trắng, Vàng nhạt...) -> Lót nền ĐEN
            bg_color = (0, 0, 0, 255) 
        else:
            # Hình in tối (Đen, Xanh đậm...) -> Lót nền TRẮNG
            bg_color = (255, 255, 255, 255)
        
        background = Image.new("RGBA", img.size, bg_color)
        background.paste(img, mask=alpha_mask)
        return background.convert("RGB")
        
    return img.convert("RGB")


def run_indexing_pro():
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)

    client = QdrantClient(path=DB_PATH)
    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=512, distance=Distance.COSINE),
        )
        logger.info("Đã tạo Database Qdrant thành công.")

    logger.info("Đang nạp AI Model (CLIP)...")
    model = SentenceTransformer(CLIP_MODEL_NAME)

    image_paths = glob(os.path.join(IMAGE_DIR, "*.[jJ][pP][gG]")) + glob(
        os.path.join(IMAGE_DIR, "*.[pP][nN][gG]")
    )
    total_images = len(image_paths)
    if total_images == 0:
        logger.warning(f"Không tìm thấy ảnh sticker nào trong {IMAGE_DIR}!")
        return

    logger.info(f"Bắt đầu quét {total_images} file sticker thiết kế...")
    start_time = time.time()
    points = []
    success_count = 0

    for img_path in image_paths:
        file_name = os.path.basename(img_path)
        try:
            full_img = load_and_preprocess_image(img_path)
            
            # Chỉ tạo 1 Vector duy nhất đại diện cho hình ảnh tĩnh của sticker
            full_vector = model.encode(full_img, show_progress_bar=False).tolist()
            
            points.append(
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, file_name + "_full")),
                    vector=full_vector,
                    payload={"file_name": file_name, "is_crop": False},
                )
            )

            success_count += 1
            if len(points) >= BATCH_SIZE:
                client.upsert(collection_name=COLLECTION_NAME, points=points)
                points = []
                logger.info(f"Tiến độ: {success_count}/{total_images}...")

        except Exception as e:
            logger.error(f"Lỗi ảnh {file_name}: {e}")

    if points:
        client.upsert(collection_name=COLLECTION_NAME, points=points)

    logger.info(f"HOÀN TẤT LƯU KHO: {time.time() - start_time:.2f} giây")


if __name__ == "__main__":
    run_indexing_pro()