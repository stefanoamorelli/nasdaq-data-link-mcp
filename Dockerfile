FROM python:3.13-slim

# Install server dependencies
RUN pip install --no-cache-dir "mcp[cli]" nasdaq-data-link pycountry

# Copy source
WORKDIR /app
COPY . .


# Ensure local package is discoverable
ENV PYTHONPATH=/app

# The server requires NASDAQ_DATA_LINK_API_KEY to be set at runtime
# Example mcpServers config for your client:
# 
# "mcpServers": {
#   "nasdaq-data-link-mcp": {
#     "command": "docker",
#     "args": [
#       "run",
#       "--rm",
#       "-i",
#       "-e", "NASDAQ_DATA_LINK_API_KEY=your-api-key-here",
#       "stefanoamorelli/nasdaq-data-link-mcp:latest"
#     ]
#   }
# }

CMD ["python", "nasdaq_data_link_mcp_os/server.py"]
