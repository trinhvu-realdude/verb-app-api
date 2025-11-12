from typing import Union
from fastapi import FastAPI, HTTPException

import requests
from bs4 import BeautifulSoup
import re
import httpx
from dotenv import load_dotenv
import os
import time

app = FastAPI()

load_dotenv()

BASE_URL = os.getenv("BASE_URL")

@app.get("/api/v1/search-word")
async def search_word(l: Union[str, None] = None, q: Union[str, None] = None):
    try:
        if not l or not q:
            return {"word": None, "data": []}

        max_retries = 3
        retry_delay = 1

        for attempt in range(1, max_retries + 1):
            url = f"{BASE_URL}/{l}/verbe/{q}.php"
            print(f"--Calling to {url} in the {attempt} time--")
            try:
                response = requests.get(url, timeout=5)
                soup = BeautifulSoup(response.content, "html.parser")
                break  # success → stop retrying
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt == max_retries:
                    raise HTTPException(
                        status_code=504,
                        detail=f"Request timed out after {max_retries} attempts: {str(e)}"
                    )
                time.sleep(retry_delay)
        else:
            raise HTTPException(status_code=504, detail="Failed to fetch after retries")

        elements = soup.find_all(["h2", "div"], class_=["mode", "tempstab", "bloc"])
        data = []
        current_section = None

        for el in elements:
            if el.name == "h2" and "mode" in el.get("class", []):
                current_section = {
                    "root": re.sub(r"<.*?>", "", el.get_text()).strip(),
                    "children": []
                }
                data.append(current_section)

            elif el.name == "div" and "tempstab" in el.get("class", []):
                if current_section is None:
                    current_section = {"root": "Default", "children": []}
                    data.append(current_section)

                tempsheader = el.find("h3", class_="tempsheader")
                tempsheader_text = tempsheader.get_text(strip=True) if tempsheader else ""

                tempscorps = el.find("div", class_="tempscorps")
                if not tempscorps:
                    continue

                table = tempscorps.find("table")
                if table:
                    rows = [
                        [td.get_text(strip=True) for td in tr.find_all("td")]
                        for tr in table.find_all("tr")
                        if any(td.get_text(strip=True) for td in tr.find_all("td"))
                    ]
                    block_data = {
                        "title": tempsheader_text,
                        "type": "table",
                        "rows": rows
                    }
                else:
                    raw_lines = tempscorps.decode_contents().split("<br/>")
                    lines = [
                        re.sub(r"\s+", " ", re.sub(r"<.*?>", "", line)).strip()
                        for line in raw_lines if re.sub(r"<.*?>", "", line).strip()
                    ]
                    block_data = {
                        "title": tempsheader_text,
                        "type": "lines",
                        "data": lines
                    }
                current_section["children"].append(block_data)
        return {
            "word": q,
            "data": data
        }
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Network error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/check-word")
async def check_word(l: Union[str, None] = None, q: Union[str, None] = None):
    with httpx.Client() as client:
        response = client.get(f"{BASE_URL}/ajx/moteur.php", params={"l": l, "q": q})
        return {"data": response.json()}