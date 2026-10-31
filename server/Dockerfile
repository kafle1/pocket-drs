# listens on 7860 as uid 1000; accounts and jobs live in /data, a host volume owned by uid 1000,
# so a redeploy keeps every result people still have open
FROM python:3.12-slim

# libglib2.0-0 and libgomp1 are what opencv-python-headless needs on slim; no ffmpeg
# binary needed, cv2.VideoCapture uses its own bundled decoder.
RUN apt-get update && apt-get install --no-install-recommends -y \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app

ENV POCKET_DRS_DATA_DIR=/data

RUN useradd --uid 1000 --create-home appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data
USER appuser

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--ws", "none"]
