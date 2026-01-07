import datetime
import requests
import re
import yaml


class OpenNotebookAPI:
    @staticmethod
    def check_health(ip):
        try:
            url = f"http://{ip}:5055/health"
            response = requests.get(url, timeout=2)
            return response.status_code == 200
        except:
            return False

    @staticmethod
    def get_notebooks(ip):
        """Fetches notebooks from the correct Open-Notebook API path."""
        try:
            url = f"http://{ip}:5055/api/notebooks"
            response = requests.get(url, timeout=5)
            return response.json()
        except Exception as e:
            print(f"[*] API Error on {ip}: {e}")
            return []

    @staticmethod
    def create_notebook(ip, name):
        try:
            url = f"http://{ip}:5055/api/notebooks"
            payload = {"name": name, "description": "Created via UI"}
            response = requests.post(url, json=payload, timeout=5)
            return response.status_code in [200, 201]
        except Exception as e:
            print(f"[*] API Error on {ip}: {e}")
            return False

    @staticmethod
    def delete_notebook(ip, notebook_id):
        try:
            url = f"http://{ip}:5055/api/notebooks/{notebook_id}"
            response = requests.delete(url, timeout=5)
            return response.status_code in [200, 204]
        except:
            return False

    @staticmethod
    def get_source(ip, source_id):
        """Fetch a single source object."""
        try:
            url = f"http://{ip}:5055/api/sources/{source_id}"
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return None
            return response.json()
        except Exception as e:
            print(f"[*] API Error on {ip}: {e}")
            return None

    @staticmethod
    def download_source(ip, source_id):
        """Download a source's original content (returns bytes)."""
        try:
            url = f"http://{ip}:5055/api/sources/{source_id}/download"
            response = requests.get(url, timeout=20)
            if response.status_code != 200:
                return None
            return response.content
        except Exception as e:
            print(f"[*] API Error on {ip}: {e}")
            return None

    @staticmethod
    def delete_source(ip, source_id):
        try:
            url = f"http://{ip}:5055/api/sources/{source_id}"
            response = requests.delete(url, timeout=10)
            return response.status_code in [200, 204]
        except Exception as e:
            print(f"[*] API Error on {ip}: {e}")
            return False

    @staticmethod
    def create_text_source(ip, notebook_id, title, content, async_processing=True):
        try:
            url = f"http://{ip}:5055/api/sources"
            payload = {
                "notebook_id": notebook_id,
                "title": title,
                "content": content,
                "type": "text",
                "async_processing": "true" if async_processing else "false",
            }
            response = requests.post(url, data=payload, timeout=20)
            return response.status_code in [200, 201]
        except Exception as e:
            print(f"[*] API Error on {ip}: {e}")
            return False

    @staticmethod
    def create_link_source(ip, notebook_id, title, url_string):
        """Creates a link source with a specific title."""
        try:
            url = f"http://{ip}:5055/api/sources/json"
            payload = {
                "notebook_id": notebook_id,
                "type": "link",
                "url": url_string,
                "title": title,
            }
            response = requests.post(url, json=payload, timeout=20)
            return response.status_code in [200, 201, 500]
        except Exception as e:
            print(f"[*] API Error on {ip}: {e}")
            return False

    @staticmethod
    def save_kb_content(ip, notebook_id, summary, data_dict):
        """Saves KB data with a custom filename: KB_YYYYMMDD_HHMMSS_summary.yaml"""
        try:
            # Sanitize summary for use in filename (remove non-alphanumeric chars)
            clean_summary = re.sub(r'[^a-zA-Z0-9]', '_', summary).lower()[:30]

            # Generate timestamp
            now = datetime.datetime.now()
            timestamp = now.strftime("%Y%m%d_%H%M%S")

            # Construct filename
            filename = f"KB_{timestamp}_{clean_summary}.yaml"
            yaml_text = yaml.dump(data_dict, sort_keys=False)

            url = f"http://{ip}:5055/api/sources"

            payload = {
                "notebook_id": notebook_id,
                "title": filename,
                "content": yaml_text,
                "type": "text",
                "async_processing": "true",
            }

            print(f"[*] DEBUG: Saving to {filename}")
            response = requests.post(url, data=payload, timeout=20)
            return response.status_code in [200, 201]

        except Exception as e:
            print(f"[!] Save Exception: {e}")
            return False

    @staticmethod
    def save_link(ip, notebook_id, title, url_string):
        """Saves a URL link to the node using the JSON endpoint (auto-generates a Link_ filename)."""
        try:
            now = datetime.datetime.now()
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            clean_title = re.sub(r'[^a-zA-Z0-9]', '_', title).lower()[:30]
            filename = f"Link_{timestamp}_{clean_title}"

            return OpenNotebookAPI.create_link_source(ip, notebook_id, filename, url_string)
        except Exception as e:
            print(f"[!] Link Save Exception: {e}")
            return False
