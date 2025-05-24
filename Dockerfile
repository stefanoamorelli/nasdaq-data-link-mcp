FROM python:3.13-slim

# Install server dependencies
RUN pip install --no-cache-dir "mcp[cli]" nasdaq-data-link pycountry

# Copy source
WORKDIR /app
COPY . .

# Default env file
COPY .env.example .env

# Ensure local package is discoverable
ENV PYTHONPATH=/app

# The server requires NASDAQ_DATA_LINK_API_KEY to be set at runtime
CMD ["mcp", "install", "nasdaq_data_link_mcp_os/server.py", "--env-file", ".env", "--name", "Nasdaq Data Link MCP Server", "--with", "nasdaq-data-link", "--with", "pycountry"]
