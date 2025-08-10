FROM nvcr.io/nvidia/tensorflow:25.02-tf2-py3
WORKDIR /app
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt
COPY . .
CMD ["python", "trainer.py"]
