FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies if needed (e.g. for some python packages)
# RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose port (Cloud Run defaults to 8080)
EXPOSE 8080

# Run Streamlit
# address=0.0.0.0 is required for container networking
CMD ["streamlit", "run", "src/dashboard/app.py", "--server.port=8080", "--server.address=0.0.0.0"]
