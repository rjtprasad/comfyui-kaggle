import os
import shutil
from pathlib import Path
from urllib.parse import urlparse, unquote
import requests
from tqdm import tqdm
import kagglehub
from kaggle_secrets import UserSecretsClient

user_secrets = UserSecretsClient()
hf_token = user_secrets.get_secret("HF_TOKEN")
civitai_token = user_secrets.get_secret("CIVITAI_TOKEN")


STAGING_DIR = "/tmp/comfyui_staging"
KAGGLE_USERNAME = "rjprasad"

class ComfyUIModelDownloader:
    def __init__(self, staging_dir: str = STAGING_DIR, username: str = KAGGLE_USERNAME):
        """Initializes the downloader and establishes the staging environment."""
        self.staging_dir = Path(staging_dir)
        self.username = username
        self._create_staging_dir()

    def _create_staging_dir(self):
        """Creates the temporary staging directory structural path if missing."""
        try:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Error creating staging directory: {e}")
            raise

    def _validate_inputs(self, models: list) -> bool:
        """Validates that the input sequence contains necessary model metadata fields.

        Args:
            models (list): List of dictionaries containing model metadata configs.

        Returns:
            bool: True if all elements match validation criteria, False otherwise.
        """
        for model in models:
            url = model.get("url")
            model_name = model.get("model_name")
            model_slug = model.get("model_slug")

            if not url or not model_slug or not model_name:
                print(f"Validation Error: Missing required properties in block: {model}")
                return False
                
        return True

    def _parse_model_info(self, model_data: dict) -> tuple:
        """Extracts systemic download properties and maps the Kaggle Hub target registry path.

        Args:
            model_data (dict): Mapping payloads containing target metadata strings.

        Returns:
            tuple: Parsed parameters containing (url, model_name, handle).
        """
        url = model_data.get("url", "")
        model_name = model_data.get("model_name", "")
        model_slug = model_data.get("model_slug", "")
        token = model_data.get("token", None)
        
        handle = f"{self.username}/{model_slug}/other/{model_name}"           # username/model_name/model_framework/model_variation/model_version
        return url, model_name, handle, token


    def _execute_download(self, url: str, headers: dict = None) -> bool:
        """Streams remote binaries safely into local storage allocations with visual tracking."""
        try:
            response = requests.get(url, stream=True, timeout=30, headers=headers)
            response.raise_for_status()
            
            file_name = None
            content_disp = response.headers.get('content-disposition')
            
            if content_disp and 'filename=' in content_disp:
                for part in content_disp.split(';'):
                    if 'filename=' in part:
                        file_name = part.split('filename=')[-1].strip('"\' ')
                        break
            
        
            if not file_name:
                parsed_url = urlparse(url)
                file_name = os.path.basename(unquote(parsed_url.path))
            
            staging_model_path = self.staging_dir / file_name
            total_size = int(response.headers.get('content-length', 0))
            
            with open(staging_model_path, "wb") as file, tqdm(
                desc=file_name[:25],
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
            ) as bar:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file.write(chunk)
                        bar.update(len(chunk))
                        
            print(f"Stored to staging with correct filename: {staging_model_path}")
            return True

        except Exception as e:
            print(f"Download Failure: {e}")
            try:
                if 'staging_model_path' in locals() and staging_model_path.exists():
                    staging_model_path.unlink()
            except Exception:
                pass
            return False

    def _push_to_kaggle(self, handle: str, model_name: str):
        """Uploads localized weights payload directory into Kaggle registry.

        Args:
            handle (str): Target Model Registry layout pointer path.
            model_name (str): Filename indicator tag for tracking logs.
        """
        try:
            kagglehub.model_upload(
                handle=handle, 
                local_model_dir=str(self.staging_dir), 
                # version_notes="v1",
                license_name="Apache 2.0"
            )
            print(f"Successfully uploaded: {model_name}")
        except Exception as e:
            print(f"Kaggle upload failed [{model_name}]: {e}")

    def _cleanup_staging(self):
        """Wipes staging space configurations to reclaim local runtime disk capacity."""
        try:
            shutil.rmtree(self.staging_dir, ignore_errors=True)
            self._create_staging_dir()
            print("Staging directory purged successfully.")
        except Exception as e:
            print(f"Clean environment warning: {e}")
    
    def download_models(self, models: list):
        """Orchestrates structured operational iterations for model migrations.

        Args:
            models (list): Structured sequence payloads to validate, pull, and transfer.
        """
        if not self._validate_inputs(models):
            return
        
        for model in models:
            url, model_name, handle, token = self._parse_model_info(model)

            # Construct the header if a token is present
            headers = None
            if token:
                headers = {"Authorization": f"Bearer {token}"}
            success = self._execute_download(url, headers=headers)
            
            if success:
                self._push_to_kaggle(handle, model_name)
                self._cleanup_staging()
            print("\n")



if __name__ == "__main__":
    models_list = [
        {
            "url" : "https://huggingface.co/Comfy-Org/Krea-2/resolve/main/diffusion_models/krea2_raw_fp8_scaled.safetensors",
            "model_name" : "krea2_raw_fp8_scaled",
            "model_slug" : "diffusion_models",
            "token": hf_token
        },
    ]

    downloader = ComfyUIModelDownloader()
    downloader.download_models(models_list)