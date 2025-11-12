# 1️⃣ Use official Python base image
FROM python:3.11-slim

# 2️⃣ Set working directory inside the container
WORKDIR /app

# 3️⃣ Copy dependency file first (for caching)
COPY requirements.txt .

# 4️⃣ Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 5️⃣ Copy your application code
COPY . .

# 6️⃣ Expose FastAPI default port
EXPOSE 8000

# 7️⃣ Run the FastAPI app with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
