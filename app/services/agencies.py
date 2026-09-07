"""Catalog of Iraqi (and named) news agencies used by the News agencies tab."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class NewsAgency:
    id: str
    label_ar: str
    label_en: str
    domains: tuple[str, ...]
    local_iraqi: bool = True


AGENCIES: tuple[NewsAgency, ...] = (
    NewsAgency("alsumaria", "السومرية", "Alsumaria", ("alsumaria.tv",), True),
    NewsAgency("baghdad24", "بغداد 24", "Baghdad 24", ("baghdad24.news",), True),
    NewsAgency(
        "jazeera",
        "الجزيرة",
        "Al Jazeera",
        ("aljazeera.net", "ajnet.me"),
        False,
    ),
    NewsAgency("ina", "واع", "INA", ("ina.iq",), True),
    NewsAgency("nina", "نينا", "NINA", ("ninanews.com",), True),
    NewsAgency("shafaq", "شفق نيوز", "Shafaq News", ("shafaq.com",), True),
    NewsAgency("almada", "المدى", "Al Mada", ("almadapaper.net",), True),
    NewsAgency("rudaw", "روداو", "Rudaw", ("rudaw.net",), True),
    NewsAgency("kurdistan24", "كوردستان 24", "Kurdistan 24", ("kurdistan24.net",), True),
    NewsAgency("mawazin", "موازين", "Mawazin", ("mawazin.net",), True),
    NewsAgency("nasnews", "ناس نيوز", "Nas News", ("nasnews.com",), True),
    NewsAgency("almirbad", "المربد", "Al-Mirbad", ("almirbad.com",), True),
    NewsAgency("alsharqiya", "الشرقية", "Al Sharqiya", ("alsharqiya.com",), True),
    NewsAgency("imn", "العراقية", "IMN", ("imn.iq", "imn.gov.iq"), True),
    NewsAgency("alforat", "الفرات", "Al-Forat", ("alforatnews.iq",), True),
    NewsAgency("utv", "يو تي في", "UTV", ("utv.iq",), True),
    NewsAgency("dijlah", "دجلة", "Dijlah", ("al-dijlah.tv", "dijlah.tv"), True),
    NewsAgency("nrt", "NRT", "NRT", ("nrttv.com",), True),
    NewsAgency("iraqinews", "Iraqi News", "Iraqi News", ("iraqinews.com",), True),
    NewsAgency("alghadpress", "الغد برس", "Al-Ghad Press", ("alghadpress.com",), True),
)

_BY_ID = {agency.id: agency for agency in AGENCIES}


def agency_catalog() -> tuple[NewsAgency, ...]:
    return AGENCIES


def selected_agencies(ids: list[str] | None) -> list[NewsAgency]:
    if not ids:
        return list(AGENCIES)
    picked = [_BY_ID[item] for item in ids if item in _BY_ID]
    return picked or list(AGENCIES)


def _host(url: str) -> str:
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    return host


def match_agency(url: str, source: str = "", platform: str = "") -> NewsAgency | None:
    if platform and platform in _BY_ID:
        return _BY_ID[platform]
    host = _host(url)
    if host:
        for agency in AGENCIES:
            if any(host == domain or host.endswith("." + domain) for domain in agency.domains):
                return agency
    source = (source or "").strip().lower()
    if source in _BY_ID:
        return _BY_ID[source]
    return None


def agency_label(url: str, source: str = "", platform: str = "") -> str:
    agency = match_agency(url, source, platform)
    return agency.label_ar if agency else ""


def public_agency_options(lang: str = "ar") -> list[dict[str, str]]:
    arabic = (lang or "ar").startswith("ar")
    return [
        {
            "id": agency.id,
            "label": agency.label_ar if arabic else agency.label_en,
        }
        for agency in AGENCIES
    ]
