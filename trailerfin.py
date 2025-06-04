import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import argparse
from dotenv import load_dotenv
import urllib.parse
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import schedule
except ImportError:
    schedule = None

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

base_path = os.getenv("SCAN_PATH")
video_filename = os.getenv("VIDEO_FILENAME")
schedule_days = int(os.getenv("SCHEDULE_DAYS", 7))
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.imdb.com/',
    'Connection': 'keep-alive',
    'DNT': '1',
    'Upgrade-Insecure-Requests': '1',
}

workers_env = os.getenv("WORKERS")
try:
    default_worker_count = int(workers_env) if workers_env is not None else 4
except ValueError:
    default_worker_count = 4

def get_trailer_video_page_url(imdb_id):
    url = f"https://www.imdb.com/title/{imdb_id}/videogallery/?sort=date,asc"
    try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            logging.error(f"Failed to fetch trailers for {imdb_id} (status {response.status_code})")
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        trailer_links = soup.find_all('a', href=re.compile(r'/video/vi\\d+'))
        if not trailer_links:
            # Broader match: any link containing '/video/vi'
            trailer_links = soup.find_all('a', href=lambda x: x and '/video/vi' in x)
        for link in trailer_links:
            if 'trailer' in link.get_text(strip=True).lower():
                video_page_url = f"https://www.imdb.com{link['href']}"
                return video_page_url
        # If no trailer found, grab the first video
        if trailer_links:
            video_page_url = f"https://www.imdb.com{trailer_links[0]['href']}"
            return video_page_url
        logging.warning(f"No video found for {imdb_id}")
        return None
    except Exception as e:
        logging.error(f"Error fetching trailers for {imdb_id}: {e}")
        return None

def get_direct_video_url_from_page(video_page_url):
    try:
        response = requests.get(video_page_url, headers=headers, timeout=20)
        if response.status_code != 200:
            logging.error(f"Failed to fetch video page: {video_page_url} (status {response.status_code})")
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__', type='application/json')
        if not script_tag:
            logging.error(f"No __NEXT_DATA__ script tag found on page: {video_page_url}")
            return None
        import json
        data = json.loads(script_tag.string)
        playback_urls = data['props']['pageProps']['videoPlaybackData']['video']['playbackURLs']
        mp4_urls = [item for item in playback_urls if item.get('videoMimeType') == 'MP4']
        if mp4_urls:
            def quality_key(item):
                if '1080' in item.get('videoDefinition', ''):
                    return 3
                if '720' in item.get('videoDefinition', ''):
                    return 2
                if '480' in item.get('videoDefinition', ''):
                    return 1
                return 0
            best = sorted(mp4_urls, key=quality_key, reverse=True)[0]
            return best['url'] + '#t=8'
        if playback_urls:
            return playback_urls[0]['url'] + '#t=8'
        logging.warning(f"No playback URLs found in JSON on page: {video_page_url}")
        return None
    except Exception as e:
        logging.error(f"Error parsing playback URLs from JSON: {e}")
        return None

def create_or_update_strm_file(folder_path, video_url):
    backdrops_path = os.path.join(folder_path, "backdrops")
    os.makedirs(backdrops_path, exist_ok=True)
    strm_path = os.path.join(backdrops_path, video_filename)
    with open(strm_path, "w") as f:
        f.write(video_url)
    logging.info(f"Updated {strm_path}")

def is_strm_expired(strm_path):
    if not os.path.exists(strm_path):
        return True
    try:
        with open(strm_path, 'r') as f:
            url = f.read().strip()
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        expires_list = query.get('Expires')
        if not expires_list:
            return True
        expires = int(expires_list[0])
        import time
        now = int(time.time())
        return now >= expires
    except Exception as e:
        logging.error(f"Error checking expiration for {strm_path}: {e}")
        return True

def process_imdb_folder(root, imdb_id):
    try:
        backdrops_path = os.path.join(root, "backdrops")
        strm_path = os.path.join(backdrops_path, video_filename)
        if not is_strm_expired(strm_path):
            logging.info(f"Trailer link still valid for {imdb_id} in {root}")
            return
        logging.info(f"Refreshing trailer for {imdb_id} in {root}")
        video_page_url = get_trailer_video_page_url(imdb_id)
        if video_page_url:
            video_url = get_direct_video_url_from_page(video_page_url)
            if video_url:
                create_or_update_strm_file(root, video_url)
    except Exception as e:
        logging.error(f"Worker error for {imdb_id} in {root}: {e}")

def scan_and_refresh_trailers(scan_path=None, worker_count=4):
    path_to_scan = scan_path if scan_path else base_path
    if not os.path.exists(path_to_scan):
        logging.error(f"Provided path does not exist: {path_to_scan}")
        return
    imdb_folders = []
    for root, dirs, files in os.walk(path_to_scan):
        match = re.search(r'\{imdb-(tt\d+)\}', root)
        if match:
            if not root.rstrip(os.sep).endswith(f'{{imdb-{match.group(1)}}}'): 
                continue
            imdb_id = match.group(1)
            imdb_folders.append((root, imdb_id))
    if not imdb_folders:
        logging.info("No IMDb folders found to process.")
        return
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_folder = {executor.submit(process_imdb_folder, root, imdb_id): (root, imdb_id) for root, imdb_id in imdb_folders}
        for future in as_completed(future_to_folder):
            root, imdb_id = future_to_folder[future]
            try:
                future.result()
            except Exception as exc:
                logging.error(f"Exception in worker for {imdb_id} in {root}: {exc}")

def run_scheduler(scan_path=None, worker_count=4):
    if not schedule:
        logging.error("schedule module not installed. Please install with 'pip install schedule'.")
        return
    def job():
        scan_and_refresh_trailers(scan_path, worker_count)
    job()
    schedule.every(schedule_days).days.do(job)
    logging.info(f"Scheduler started. Running every {schedule_days} day(s).")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan and refresh IMDb trailers.")
    parser.add_argument('--dir', type=str, help='Directory to scan (defaults to /mnt/plex)')
    parser.add_argument('--schedule', action='store_true', help='Run as a weekly scheduled job')
    parser.add_argument('--workers', type=int, default=default_worker_count, help=f'Number of worker threads (default: {default_worker_count})')
    args = parser.parse_args()
    if args.schedule:
        run_scheduler(args.dir, args.workers)
    else:
        scan_and_refresh_trailers(args.dir, args.workers)
