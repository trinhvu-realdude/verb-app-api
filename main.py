from typing import Optional, Union
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
import re
import httpx
from dotenv import load_dotenv
import os
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException

from constant import PART_OF_SPEECH_MAP

load_dotenv()

BASE_URL = os.getenv("BASE_URL")
FREE_DICTIONARY_URL = os.getenv("FREE_DICTIONARY_URL")

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(5.0),
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20
        ),
        follow_redirects=True
    )
    yield
    await app.state.http_client.aclose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def normalize_part_of_speech(language: str, part_of_speech: str):
    if not part_of_speech:
        return None

    language_map = PART_OF_SPEECH_MAP.get(language)

    if not language_map:
        return part_of_speech

    return language_map.get(part_of_speech.lower(), part_of_speech)

@app.get("/api/v1/search-word")
async def search_word(l: Union[str, None] = None, q: Union[str, None] = None):
    if not l or not q:
        return {"word": q, "data": []}

    keyword = q.strip().replace("'", "_").replace(" ", "_")
    url = f"{BASE_URL}/{l}/verbe/{keyword}.php"

    max_retries = 3
    soup = None

    for attempt in range(1, max_retries + 1):
        try:
            print(f"--Calling to {url} in the {attempt} time--")

            response = await app.state.http_client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")
            break

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            print(f"Request failed ({attempt}/{max_retries}): {e}")

            if attempt == max_retries:
                return {"word": q, "data": []}

            await asyncio.sleep(1)

        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            print(f"HTTP request error: {e}")
            return {"word": q, "data": []}

        except Exception as e:
            print(f"Unexpected error: {e}")
            return {"word": q, "data": []}

    if soup is None:
        return {"word": q, "data": []}

    try:
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
                    # rows = [
                    #     [td.get_text(strip=True) for td in tr.find_all("td")]
                    #     for tr in table.find_all("tr")
                    #     if any(td.get_text(strip=True) for td in tr.find_all("td"))
                    # ]
                    rows = [
                        [
                            re.sub(r"\s+", " ", td.decode_contents()).strip()
                            for td in tr.find_all("td")
                        ]
                        for tr in table.find_all("tr")
                        if any(td.get_text(strip=True) for td in tr.find_all("td"))
                    ]
                    block_data = {
                        "title": tempsheader_text,
                        "type": "table",
                        "data": rows
                    }
                else:
                    raw_lines = tempscorps.decode_contents().split("<br/>")
                    lines = [
                        re.sub(r"\s+", " ", line).strip()
                        for line in raw_lines if re.sub(r"<.*?>", "", line).strip()
                    ]
                    block_data = {
                        "title": tempsheader_text,
                        "type": "lines",
                        "data": lines
                    }
                current_section["children"].append(block_data)
        return {"word": q, "data": data}
    except Exception as e:
        print(f"Error parsing word data: {e}")
        return {"word": q, "data": []}

@app.get("/api/v1/check-word")
async def check_word(l: Union[str, None] = None, q: Union[str, None] = None):
    with httpx.Client() as client:
        response = client.get(f"{BASE_URL}/ajx/moteur.php", params={"l": l, "q": q})
        return {"data": response.json()}

@app.get("/api/v1/get-phonetic")
async def get_phonetic(l: Optional[str] = None, w: Optional[str] = None, pos: Optional[str] = None):
    if not w:
        return {
            "language": l,
            "word": w,
            "pronunciations": []
        }

    url = f"{FREE_DICTIONARY_URL}{l}/{w.strip()}"

    try:
        response = await app.state.http_client.get(url)
        response.raise_for_status()

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Dictionary API request timed out"
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail="Error fetching phonetic data"
        )

    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Dictionary API connection error: {str(e)}"
        )

    data = response.json()
    entries = data.get("entries", [])

    # Convert frontend partOfSpeech to English value
    normalized_pos = normalize_part_of_speech(l, pos)

    pronunciations = {}

    for entry in entries:
        pos = entry.get("partOfSpeech")

        if not pos:
            continue

        # Filter by normalized partOfSpeech
        if normalized_pos and pos != normalized_pos:
            continue

        if pos not in pronunciations:
            pronunciations[pos] = None

        for pronunciation in entry.get("pronunciations", []):
            if (
                pronunciation.get("type") == "ipa"
                and pronunciation.get("text")
            ):
                pronunciations[pos] = pronunciation["text"]
                break

    return {
        "language": l,
        "word": w,
        "pronunciations": [
            {
                "partOfSpeech": pos,
                "phonetic": phonetic
            }
            for pos, phonetic in pronunciations.items()
        ]
    }

@app.get("/api/v1/synonyms-antonyms")
async def synonyms_antonyms(l: Optional[str] = None, w: Optional[str] = None, pos: Optional[str] = None):
    if not w or not w.strip():
        return {
            "language": l,
            "word": w,
            "synonyms": [],
            "antonyms": []
        }

    url = f"{FREE_DICTIONARY_URL}{l}/{w.strip()}"

    try:
        response = await app.state.http_client.get(url)
        response.raise_for_status()

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Dictionary API request timed out"
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail="Error fetching synonyms and antonyms data"
        )

    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Dictionary API connection error: {str(e)}"
        )

    data = response.json()
    entries = data.get("entries") or []

    normalized_pos = normalize_part_of_speech(l, pos)

    synonyms = set()
    antonyms = set()

    for entry in entries:
        entry_pos = entry.get("partOfSpeech")

        if normalized_pos and entry_pos != normalized_pos:
            continue

        synonyms.update(entry.get("synonyms") or [])
        antonyms.update(entry.get("antonyms") or [])

    return {
        "language": l,
        "word": w,
        "synonyms": list(synonyms),
        "antonyms": list(antonyms)
    }
