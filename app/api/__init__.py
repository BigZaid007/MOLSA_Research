from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import logging

logger = logging.getLogger(__name__)

# Translation service
def get_translations(language: str):
    import json
    translations_path = f"app/translations/{language}.json"
    try:
        with open(translations_path) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Translations file not found for language: {language}")
        return {}


app = FastAPI()


@app.get("/")
async def read_root(request: Request):
    language = request.query_params.get("lang", "en")
    translations = get_translations(language)
    
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="{language}" dir="{ 'rtl' if language == 'ar' else 'ltr' }">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Research Data Fetcher</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
        <style>
            [x-cloak] {{ display: none !important; }}
        </style>
    </head>
    <body class="bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
        <div id="app" x-data="app()" x-cloak>
            <div class="container mx-auto px-4 py-8">
                <header class="flex justify-between items-center mb-8">
                    <h1 class="text-3xl font-bold">{translations.appName || 'Research Data Fetcher'}</h1>
                    <div class="flex items-center space-x-4">
                        <button @click="toggleTheme" class="p-2 rounded-lg bg-gray-200 dark:bg-gray-700">
                            <span x-text="theme === 'dark' ? '☀️' : '🌙'"></span>
                        </button>
                        <select x-model="language" @change="changeLanguage" class="p-2 rounded-lg bg-gray-200 dark:bg-gray-700">
                            <option value="en">English</option>
                            <option value="ar">العربية</option>
                        </select>
                    </div>
                </header>
                
                <main>
                    <div class="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 mb-8">
                        <h2 class="text-xl font-semibold mb-4">{translations.search || 'Search'}</h2>
                        <div class="flex flex-col md:flex-row gap-4">
                            <input type="text" x-model="topic" placeholder="Enter topic to research..." 
                                class="flex-1 p-2 rounded-lg border dark:bg-gray-700 dark:border-gray-600">
                            <select x-model="selectedSources" multiple class="p-2 rounded-lg border dark:bg-gray-700 dark:border-gray-600">
                                <option value="google">Google</option>
                                <option value="rss">RSS Feeds</option>
                                <option value="reddit">Reddit</option>
                            </select>
                            <input type="number" x-model="maxResults" placeholder="Max results" 
                                class="w-24 p-2 rounded-lg border dark:bg-gray-700 dark:border-gray-600">
                            <button @click="search" class="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600">
                                {translations.search || 'Search'}
                            </button>
                        </div>
                    </div>
                    
                    <div x-show="loading" class="text-center py-8">
                        <div class="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
                        <p class="mt-2" x-text="loadingMessage"></p>
                    </div>
                    
                    <div x-show="results.length > 0" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        <template x-for="result in results" :key="result.id">
                            <div class="bg-white dark:bg-gray-800 rounded-lg shadow-md overflow-hidden">
                                <div class="p-4">
                                    <div class="flex items-start justify-between mb-2">
                                        <h3 class="font-semibold text-lg line-clamp-2" x-text="result.title"></h3>
                                        <span class="text-xs px-2 py-1 bg-gray-200 dark:bg-gray-700 rounded" x-text="result.source"></span>
                                    </div>
                                    <p class="text-gray-600 dark:text-gray-400 text-sm line-clamp-3" x-text="result.description"></p>
                                    <div class="flex items-center justify-between mt-4 text-xs text-gray-500 dark:text-gray-400">
                                        <span x-text="result.source"></span>
                                        <span x-text="formatDate(result.published_date)"></span>
                                    </div>
                                    <div class="mt-4">
                                        <a :href="result.url" target="_blank" class="text-blue-500 hover:text-blue-600 text-sm">
                                            Read more →
                                        </a>
                                    </div>
                                </div>
                            </div>
                        </template>
                    </div>
                    
                    <div x-show="results.length === 0 && !loading" class="text-center py-8 text-gray-500 dark:text-gray-400">
                        {translations.noResults || 'No results found. Try a different search.'}
                    </div>
                </main>
            </div>
            
            <script>
                function app() {
                    return {
                        topic: '',
                        selectedSources: ['google', 'rss'],
                        maxResults: 10,
                        results: [],
                        loading: false,
                        loadingMessage: 'Searching...',
                        language: 'en',
                        theme: localStorage.getItem('theme') || 'light',
                        
                        async search() {
                            if (!this.topic.trim()) return;
                            
                            this.loading = true;
                            this.loadingMessage = 'Searching...';
                            
                            try {
                                const response = await fetch('/api/search', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        topic: this.topic,
                                        sources: this.selectedSources,
                                        max_results: this.maxResults
                                    })
                                });
                                
                                const data = await response.json();
                                
                                if (data.task_id) {
                                    this.loadingMessage = 'Processing results...';
                                    await this.pollResults(data.task_id);
                                }
                            } catch (error) {
                                console.error('Search error:', error);
                                this.loading = false;
                            }
                        },
                        
                        async pollResults(taskId) {
                            let attempts = 0;
                            const maxAttempts = 30;
                            
                            const poll = async () => {
                                attempts++;
                                
                                try {
                                    const response = await fetch(`/api/results/${taskId}`);
                                    const data = await response.json();
                                    
                                    if (data.results && data.results.length > 0) {
                                        this.results = data.results;
                                        this.loading = false;
                                    } else if (data.status === 'completed') {
                                        this.loading = false;
                                    } else {
                                        if (attempts < maxAttempts) {
                                            setTimeout(poll, 1000);
                                        } else {
                                            this.loading = false;
                                            console.error('Search timeout');
                                        }
                                    }
                                } catch (error) {
                                    console.error('Polling error:', error);
                                    this.loading = false;
                                }
                            };
                            
                            poll();
                        },
                        
                        changeLanguage() {
                            window.location.search = `lang=${this.language}`;
                        },
                        
                        toggleTheme() {
                            this.theme = this.theme === 'dark' ? 'light' : 'dark';
                            localStorage.setItem('theme', this.theme);
                            document.documentElement.classList.toggle('dark');
                        },
                        
                        formatDate(dateString) {
                            if (!dateString) return '';
                            return new Date(dateString).toLocaleDateString();
                        }
                    };
                }
            </script>
        </div>
    </body>
    </html>
    """, media_type="text/html")


@app.get("/api/translations/{language}")
async def get_translations_endpoint(language: str):
    translations = get_translations(language)
    return {"language": language, "translations": translations}


@app.get("/health")
async def health_check():
    return {"status": "ok"}
