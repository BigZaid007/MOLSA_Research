from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

class ContentType(str, Enum):
    NEWS = "news"
    BLOG = "blog"
    WEBSITE = "website"
    RSS = "rss"
    DOCUMENTATION = "documentation"
    FORUM = "forum"
    SOCIAL = "social"

class Language(str, Enum):
    EN = "en"
    AR = "ar"

class ResearchItem(BaseModel):
    id: Optional[str] = None
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    image: Optional[str] = None
    url: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    published_date: Optional[datetime] = None
    author: Optional[str] = None
    language: Language = Language.EN
    content: Optional[str] = None
    content_type: ContentType
    keywords: Optional[List[str]] = None
    scraped_at: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    @property
    def domain(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self.url).netloc

    @property
    def is_valid(self) -> bool:
        return bool(self.title and self.url)


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: Optional[str] = None
    source: str
    published_date: Optional[datetime] = None

    @property
    def is_valid(self) -> bool:
        return bool(self.title and self.url)


class SearchRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    sources: List[str] = Field(default_factory=list)
    max_results: int = Field(default=10, ge=1, le=50)
    content_type: str = "all"
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    province: Optional[str] = None
