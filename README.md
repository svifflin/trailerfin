# Trailerfin

Trailerfin is a tool for automatically retrieving and refreshing IMDb trailer links for your media library.
Instead of downloading the the trailer locally, it will create a .strm file that Jellyfin can use to play the video.  
It will checck the expiration of the link and only update when the link has expired

## Features
- Scans directories for IMDb IDs and updates trailer links
- Fetches the latest trailer or video from IMDb
- Supports scheduled automatic refreshes
- Configurable via environment variables
- Docker and Docker Compose support
- Robust logging for monitoring and troubleshooting

## Requirements
- Python 3.11+
- Docker (recommended)
- IMDb IDs in your media folder structure

## Setup

### 1. Clone the repository
```sh
git clone https://github.com/Pukabyte/trailerfin.git
cd trailerfin
```

### 2. Configure Environment Variables
Create a `.env` file in the project root with the following variables:

```env
SCAN_PATH=/path/to/your/media
VIDEO_FILENAME=trailer.strm
SCHEDULE_DAYS=7
```

- `SCAN_PATH`: Directory to scan for IMDb IDs
- `VIDEO_FILENAME`: Name of the .strm file to update
- `SCHEDULE_DAYS`: Interval in days for scheduled refresh

### 3. Build and Run with Docker

#### Build the Docker image
```sh
docker build -t trailerfin .
```

#### Run the container
```sh
docker run --env-file .env -v /path/to/your/media:/mnt/plex trailerfin
```

### 4. Using Docker Compose

A sample `docker-compose.yml` is provided:

```yaml
services:
  trailerfin:
    build: .
    container_name: trailerfin
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Etc/UTC
    volumes:
      - /mnt:/mnt # Make sure this directory is where your content can be found in
      - /opt/trailerfin:/app
      - /etc/localtime:/etc/localtime:ro
    restart: unless-stopped
```

Start with:
```sh
docker-compose up -d
```

## Usage

### Manual Run
```sh
python trailerfin.py --dir /path/to/your/media
```

### Scheduled Run (default in Docker)
```sh
python trailerfin.py --schedule
```

## Logging
Logs are output to stdout and can be viewed with Docker logs or Compose logs.

## License
MIT License 