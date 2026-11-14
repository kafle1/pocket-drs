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
# ultralytics pulls in the full opencv-python, which shares the cv2 folder with the headless build and needs
# libGL, which slim doesn't have; put the pinned headless build back on its own
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir --no-deps --force-reinstall "$(grep -i '^opencv-python-headless' requirements.txt)"

COPY app app
# the detector weights are not in git; build them as models/DETECTOR.md says before building the image
COPY models/cricket_ball.pt models/

ENV POCKET_DRS_DATA_DIR=/data

RUN useradd --uid 1000 --create-home appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data
USER appuser

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--ws", "none"]
