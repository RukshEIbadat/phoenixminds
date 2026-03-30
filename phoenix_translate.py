"""
PhoenixMinds Universal Translation Engine v1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Architecture:
  Tier 1 — Groq LLaMA-3.3-70B   (ultra-fast, free, 200+ langs, best for clinical context)
  Tier 2 — Claude Sonnet 4.6    (highest accuracy, nuance, medical terminology)
  Tier 3 — GPT-4o               (broad fallback, 200+ langs)
  Tier 4 — Google Cloud NMT     (249 languages, 0.09s median, highest coverage)
  Tier 5 — DeepL API            (European + clinical pairs, best BLEU scores)
  Tier 6 — NLLB-200 (HuggingFace REST) (open-source backbone, 200 langs, free)
  Tier 7 — Rule-based passthrough (emergency fallback)

Routing Logic (Apple-style Live Translation for web):
  - Clinical/medical content  → Claude → GPT-4o → DeepL
  - European language pairs   → DeepL → Google  → Groq
  - Asian + rare languages    → Groq  → Google  → NLLB-200
  - Real-time UI strings      → Groq  (fastest, 300ms)
  - Batch document translation→ Google → Claude

Usage:
  from phoenix_translate import PhoenixTranslator
  t = PhoenixTranslator()
  result = t.translate("Hello, how are you?", target="Urdu")
  print(result.text)  # اردو میں ترجمہ

Reusable across:
  - PhoenixMinds (child development platform)
  - Phoenix International products
  - Phoenix Group research systems
  - MARS-MINDS (multilingual mission data)
"""

import os
import time
import json
import hashlib
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# ── LANGUAGE REGISTRY ─────────────────────────────────────────────────────────
# Maps language codes/names to provider-specific codes
LANG_REGISTRY: Dict[str, Dict] = {
    # code: {name, google_code, deepl_code, groq_hint, nllb_code, rtl, clinical_ok, deepl_supported}
    "en":  {"name":"English",       "google":"en",   "deepl":"EN-US","nllb":"eng_Latn","rtl":False,"clinical":True,"deepl_ok":True},
    "ur":  {"name":"Urdu",          "google":"ur",   "deepl":None,   "nllb":"urd_Arab","rtl":True, "clinical":True,"deepl_ok":False},
    "ar":  {"name":"Arabic",        "google":"ar",   "deepl":"AR",   "nllb":"arb_Arab","rtl":True, "clinical":True,"deepl_ok":True},
    "hi":  {"name":"Hindi",         "google":"hi",   "deepl":None,   "nllb":"hin_Deva","rtl":False,"clinical":True,"deepl_ok":False},
    "bn":  {"name":"Bengali",       "google":"bn",   "deepl":None,   "nllb":"ben_Beng","rtl":False,"clinical":False,"deepl_ok":False},
    "pa":  {"name":"Punjabi",       "google":"pa",   "deepl":None,   "nllb":"pan_Guru","rtl":False,"clinical":False,"deepl_ok":False},
    "sd":  {"name":"Sindhi",        "google":"sd",   "deepl":None,   "nllb":"snd_Arab","rtl":True, "clinical":False,"deepl_ok":False},
    "ps":  {"name":"Pashto",        "google":"ps",   "deepl":None,   "nllb":"pbt_Arab","rtl":True, "clinical":False,"deepl_ok":False},
    "ta":  {"name":"Tamil",         "google":"ta",   "deepl":None,   "nllb":"tam_Taml","rtl":False,"clinical":False,"deepl_ok":False},
    "te":  {"name":"Telugu",        "google":"te",   "deepl":None,   "nllb":"tel_Telu","rtl":False,"clinical":False,"deepl_ok":False},
    "ml":  {"name":"Malayalam",     "google":"ml",   "deepl":None,   "nllb":"mal_Mlym","rtl":False,"clinical":False,"deepl_ok":False},
    "si":  {"name":"Sinhala",       "google":"si",   "deepl":None,   "nllb":"sin_Sinh","rtl":False,"clinical":False,"deepl_ok":False},
    "ne":  {"name":"Nepali",        "google":"ne",   "deepl":None,   "nllb":"npi_Deva","rtl":False,"clinical":False,"deepl_ok":False},
    "fa":  {"name":"Farsi",         "google":"fa",   "deepl":None,   "nllb":"pes_Arab","rtl":True, "clinical":False,"deepl_ok":False},
    "tr":  {"name":"Turkish",       "google":"tr",   "deepl":"TR",   "nllb":"tur_Latn","rtl":False,"clinical":True,"deepl_ok":True},
    "he":  {"name":"Hebrew",        "google":"iw",   "deepl":None,   "nllb":"heb_Hebr","rtl":True, "clinical":False,"deepl_ok":False},
    "ku":  {"name":"Kurdish",       "google":"ku",   "deepl":None,   "nllb":"ckb_Arab","rtl":False,"clinical":False,"deepl_ok":False},
    "fr":  {"name":"French",        "google":"fr",   "deepl":"FR",   "nllb":"fra_Latn","rtl":False,"clinical":True,"deepl_ok":True},
    "de":  {"name":"German",        "google":"de",   "deepl":"DE",   "nllb":"deu_Latn","rtl":False,"clinical":True,"deepl_ok":True},
    "es":  {"name":"Spanish",       "google":"es",   "deepl":"ES",   "nllb":"spa_Latn","rtl":False,"clinical":True,"deepl_ok":True},
    "pt":  {"name":"Portuguese",    "google":"pt",   "deepl":"PT-BR","nllb":"por_Latn","rtl":False,"clinical":True,"deepl_ok":True},
    "ru":  {"name":"Russian",       "google":"ru",   "deepl":"RU",   "nllb":"rus_Cyrl","rtl":False,"clinical":True,"deepl_ok":True},
    "it":  {"name":"Italian",       "google":"it",   "deepl":"IT",   "nllb":"ita_Latn","rtl":False,"clinical":True,"deepl_ok":True},
    "nl":  {"name":"Dutch",         "google":"nl",   "deepl":"NL",   "nllb":"nld_Latn","rtl":False,"clinical":True,"deepl_ok":True},
    "pl":  {"name":"Polish",        "google":"pl",   "deepl":"PL",   "nllb":"pol_Latn","rtl":False,"clinical":True,"deepl_ok":True},
    "uk":  {"name":"Ukrainian",     "google":"uk",   "deepl":"UK",   "nllb":"ukr_Cyrl","rtl":False,"clinical":False,"deepl_ok":True},
    "el":  {"name":"Greek",         "google":"el",   "deepl":"EL",   "nllb":"ell_Grek","rtl":False,"clinical":False,"deepl_ok":True},
    "zh":  {"name":"Chinese",       "google":"zh-CN","deepl":"ZH",   "nllb":"zho_Hans","rtl":False,"clinical":True,"deepl_ok":True},
    "ja":  {"name":"Japanese",      "google":"ja",   "deepl":"JA",   "nllb":"jpn_Jpan","rtl":False,"clinical":True,"deepl_ok":True},
    "ko":  {"name":"Korean",        "google":"ko",   "deepl":"KO",   "nllb":"kor_Hang","rtl":False,"clinical":False,"deepl_ok":True},
    "vi":  {"name":"Vietnamese",    "google":"vi",   "deepl":None,   "nllb":"vie_Latn","rtl":False,"clinical":False,"deepl_ok":False},
    "th":  {"name":"Thai",          "google":"th",   "deepl":None,   "nllb":"tha_Thai","rtl":False,"clinical":False,"deepl_ok":False},
    "id":  {"name":"Indonesian",    "google":"id",   "deepl":"ID",   "nllb":"ind_Latn","rtl":False,"clinical":False,"deepl_ok":True},
    "ms":  {"name":"Malay",         "google":"ms",   "deepl":None,   "nllb":"zsm_Latn","rtl":False,"clinical":False,"deepl_ok":False},
    "my":  {"name":"Myanmar",       "google":"my",   "deepl":None,   "nllb":"mya_Mymr","rtl":False,"clinical":False,"deepl_ok":False},
    "sw":  {"name":"Kiswahili",     "google":"sw",   "deepl":None,   "nllb":"swh_Latn","rtl":False,"clinical":False,"deepl_ok":False},
    "am":  {"name":"Amharic",       "google":"am",   "deepl":None,   "nllb":"amh_Ethi","rtl":False,"clinical":False,"deepl_ok":False},
    "ha":  {"name":"Hausa",         "google":"ha",   "deepl":None,   "nllb":"hau_Latn","rtl":False,"clinical":False,"deepl_ok":False},
    "yo":  {"name":"Yoruba",        "google":"yo",   "deepl":None,   "nllb":"yor_Latn","rtl":False,"clinical":False,"deepl_ok":False},
    "ig":  {"name":"Igbo",          "google":"ig",   "deepl":None,   "nllb":"ibo_Latn","rtl":False,"clinical":False,"deepl_ok":False},
    "zu":  {"name":"Zulu",          "google":"zu",   "deepl":None,   "nllb":"zul_Latn","rtl":False,"clinical":False,"deepl_ok":False},
    "so":  {"name":"Somali",        "google":"so",   "deepl":None,   "nllb":"som_Latn","rtl":False,"clinical":False,"deepl_ok":False},
}

def resolve_lang(lang_input: str) -> Optional[Dict]:
    """Resolve language by code, name, or partial match"""
    if not lang_input: return LANG_REGISTRY.get("en")
    lower = lang_input.lower().strip()
    # Direct code match
    if lower in LANG_REGISTRY: return LANG_REGISTRY[lower]
    # Name match
    for code, info in LANG_REGISTRY.items():
        if info["name"].lower() == lower: return {**info, "_code": code}
    # Partial name match
    for code, info in LANG_REGISTRY.items():
        if lower in info["name"].lower() or info["name"].lower() in lower:
            return {**info, "_code": code}
    # Return None if no match — will use LLM with language name directly
    return None

@dataclass
class TranslationResult:
    text: str
    source_lang: str
    target_lang: str
    provider: str
    latency_ms: float
    confidence: float = 1.0
    cached: bool = False
    error: Optional[str] = None

class TranslationCache:
    """In-memory LRU cache for translations"""
    def __init__(self, max_size: int = 2000):
        self._cache: Dict[str, TranslationResult] = {}
        self._max = max_size
    def _key(self, text: str, target: str, source: str) -> str:
        return hashlib.md5(f"{source}|{target}|{text[:200]}".encode()).hexdigest()
    def get(self, text: str, target: str, source: str = "auto") -> Optional[TranslationResult]:
        return self._cache.get(self._key(text, target, source))
    def set(self, text: str, target: str, source: str, result: TranslationResult):
        if len(self._cache) >= self._max:
            # Remove oldest 200 entries
            oldest = list(self._cache.keys())[:200]
            for k in oldest: del self._cache[k]
        self._cache[self._key(text, target, source)] = result

class PhoenixTranslator:
    """
    Universal Translation Engine for Phoenix Group platforms.
    Intelligent cascade routing with caching and fallback.
    """
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.cache = TranslationCache()
        self._init_providers()

    def _init_providers(self):
        """Initialise all available providers"""
        self.providers_available = {}

        # Groq (LLaMA-3.3-70B) — fastest, 300ms, free tier
        try:
            from groq import Groq
            self._groq = Groq(api_key=os.environ.get("GROQ_API_KEY",""))
            self.providers_available["groq"] = True
        except Exception:
            self._groq = None
            self.providers_available["groq"] = False

        # Anthropic Claude — most accurate for clinical/medical
        try:
            import anthropic
            self._claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY",""))
            self.providers_available["claude"] = True
        except Exception:
            self._claude = None
            self.providers_available["claude"] = False

        # OpenAI GPT-4o — broad fallback
        try:
            from openai import OpenAI
            self._openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY",""))
            self.providers_available["openai"] = True
        except Exception:
            self._openai = None
            self.providers_available["openai"] = False

        # Google Cloud Translation API (v2 basic — key-based)
        try:
            import requests as req
            self._requests = req
            gcsk = os.environ.get("GOOGLE_CSE_API_KEY") or os.environ.get("GOOGLE_API_KEY","")
            if gcsk:
                self._google_key = gcsk
                self.providers_available["google"] = True
            else:
                self.providers_available["google"] = False
        except Exception:
            self.providers_available["google"] = False

        # DeepL API
        try:
            import deepl as deepl_lib
            dk = os.environ.get("DEEPL_API_KEY","")
            if dk:
                self._deepl = deepl_lib.Translator(dk)
                self.providers_available["deepl"] = True
            else:
                self.providers_available["deepl"] = False
        except Exception:
            self.providers_available["deepl"] = False

        # NLLB-200 via HuggingFace Inference API (free)
        hf_key = os.environ.get("HUGGINGFACE_API_KEY","")
        self._hf_key = hf_key
        self.providers_available["nllb"] = bool(hf_key)

        logger.info(f"PhoenixTranslator ready. Providers: {[k for k,v in self.providers_available.items() if v]}")

    def _choose_route(self, target_info: Optional[Dict], is_clinical: bool, text_len: int) -> list:
        """Determine provider cascade order based on language + content type"""
        if not target_info:
            # Unknown language — LLM only
            return ["groq","claude","openai"]

        deepl_ok = target_info.get("deepl_ok", False)
        is_clinical_lang = target_info.get("clinical", False)

        if is_clinical and is_clinical_lang and deepl_ok:
            # Clinical content in DeepL-supported language
            return ["claude","deepl","openai","google","groq"]
        elif deepl_ok:
            # European language, general content
            return ["groq","deepl","google","claude","openai"]
        elif text_len > 500:
            # Long text — Google batch first
            return ["google","groq","claude","openai","nllb"]
        else:
            # Short text, non-European
            return ["groq","google","claude","openai","nllb"]

    def translate(
        self,
        text: str,
        target: str,
        source: str = "auto",
        is_clinical: bool = False,
        preserve_formatting: bool = True,
        context: str = ""
    ) -> TranslationResult:
        """
        Translate text with intelligent provider routing.
        
        Args:
            text: Text to translate
            target: Target language (code like 'ur', 'ar' or name like 'Urdu', 'Arabic')
            source: Source language code or 'auto'
            is_clinical: Enable medical/clinical accuracy mode (uses Claude/DeepL first)
            preserve_formatting: Preserve HTML/markdown formatting
            context: Additional context for LLM providers (e.g., 'This is a clinical report')
        
        Returns:
            TranslationResult with .text property
        """
        if not text or not text.strip():
            return TranslationResult(text=text, source_lang=source, target_lang=target, provider="passthrough", latency_ms=0)

        # Resolve target language
        target_info = resolve_lang(target)
        target_name = target_info["name"] if target_info else target

        # Check if target == source (skip if English requested and text appears English)
        if target in ("en","English") and source == "auto":
            # Quick heuristic: if mostly ASCII and no obvious non-English characters, skip
            ascii_ratio = sum(1 for c in text if ord(c) < 128) / len(text)
            if ascii_ratio > 0.92:
                return TranslationResult(text=text, source_lang="en", target_lang="en", provider="passthrough", latency_ms=0)

        # Cache check
        cached = self.cache.get(text, target_name, source)
        if cached:
            cached.cached = True
            return cached

        # Choose routing cascade
        route = self._choose_route(target_info, is_clinical, len(text))
        t0 = time.perf_counter()

        for provider in route:
            if not self.providers_available.get(provider): continue
            try:
                translated = self._call_provider(provider, text, target_name, target_info, source, is_clinical, context, preserve_formatting)
                if translated and translated.strip():
                    latency = (time.perf_counter() - t0) * 1000
                    result = TranslationResult(
                        text=translated, source_lang=source, target_lang=target_name,
                        provider=provider, latency_ms=round(latency,1)
                    )
                    self.cache.set(text, target_name, source, result)
                    return result
            except Exception as e:
                logger.warning(f"Provider {provider} failed: {e}")
                continue

        # All providers failed — return original
        latency = (time.perf_counter() - t0) * 1000
        return TranslationResult(
            text=text, source_lang=source, target_lang=target_name,
            provider="passthrough", latency_ms=round(latency,1),
            error="All providers failed"
        )

    def _call_provider(self, provider: str, text: str, target_name: str, target_info: Optional[Dict],
                        source: str, is_clinical: bool, context: str, preserve_formatting: bool) -> Optional[str]:
        """Call a specific translation provider"""

        if provider == "groq":
            return self._translate_llm(
                text, target_name, source, is_clinical, context, preserve_formatting,
                client=self._groq, model="llama-3.3-70b-versatile", provider="groq"
            )

        elif provider == "claude":
            return self._translate_llm(
                text, target_name, source, is_clinical, context, preserve_formatting,
                client=self._claude, model="claude-haiku-4-5", provider="claude"
            )

        elif provider == "openai":
            return self._translate_llm(
                text, target_name, source, is_clinical, context, preserve_formatting,
                client=self._openai, model="gpt-4o-mini", provider="openai"
            )

        elif provider == "google":
            return self._translate_google(text, target_info, source)

        elif provider == "deepl":
            return self._translate_deepl(text, target_info)

        elif provider == "nllb":
            return self._translate_nllb(text, target_info, source)

        return None

    def _build_prompt(self, text: str, target_name: str, source: str, is_clinical: bool,
                      context: str, preserve_formatting: bool) -> str:
        """Build optimal translation prompt"""
        clinical_note = """
CRITICAL: This is clinical/medical content. Maintain precise medical terminology.
Preserve all drug names, dosages, diagnostic codes, and clinical terms exactly.
Use professionally accepted medical translations in the target language.""" if is_clinical else ""

        formatting_note = "Preserve all HTML tags, markdown formatting, and structure exactly." if preserve_formatting else ""
        context_note = f"Context: {context}" if context else ""
        source_note = f"Source language: {source}" if source and source != "auto" else "Auto-detect source language."

        return f"""Translate the following text to {target_name}. Return ONLY the translated text with no preamble, explanation, or quotes.{clinical_note}{formatting_note}{context_note}
{source_note}

Text to translate:
{text}"""

    def _translate_llm(self, text: str, target_name: str, source: str, is_clinical: bool,
                       context: str, preserve_formatting: bool, client, model: str, provider: str) -> Optional[str]:
        """Generic LLM translation handler"""
        prompt = self._build_prompt(text, target_name, source, is_clinical, context, preserve_formatting)

        if provider == "claude":
            r = client.messages.create(
                model=model, max_tokens=4000, temperature=0.05,
                messages=[{"role":"user","content":prompt}]
            )
            return r.content[0].text.strip()
        else:
            # Groq + OpenAI share the chat completions interface
            r = client.chat.completions.create(
                model=model, max_tokens=4000, temperature=0.05,
                messages=[{"role":"user","content":prompt}]
            )
            return r.choices[0].message.content.strip()

    def _translate_google(self, text: str, target_info: Optional[Dict], source: str) -> Optional[str]:
        """Google Cloud Translation API v2"""
        if not target_info: return None
        gc = target_info.get("google")
        if not gc: return None
        url = "https://translation.googleapis.com/language/translate/v2"
        params = {"key": self._google_key, "q": text, "target": gc, "format": "text"}
        if source and source != "auto": params["source"] = source
        resp = self._requests.post(url, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return data["data"]["translations"][0]["translatedText"]

    def _translate_deepl(self, text: str, target_info: Optional[Dict]) -> Optional[str]:
        """DeepL API"""
        if not target_info: return None
        code = target_info.get("deepl")
        if not code: return None
        result = self._deepl.translate_text(text, target_lang=code)
        return result.text

    def _translate_nllb(self, text: str, target_info: Optional[Dict], source: str) -> Optional[str]:
        """Meta NLLB-200 via HuggingFace Inference API"""
        if not target_info: return None
        nllb_code = target_info.get("nllb")
        if not nllb_code: return None
        # Determine source NLLB code
        source_info = LANG_REGISTRY.get(source, {}) if source != "auto" else {}
        src_nllb = source_info.get("nllb","eng_Latn")
        api_url = "https://api-inference.huggingface.co/models/facebook/nllb-200-distilled-600M"
        headers = {"Authorization": f"Bearer {self._hf_key}"}
        payload = {
            "inputs": text,
            "parameters": {"src_lang": src_nllb, "tgt_lang": nllb_code}
        }
        resp = self._requests.post(api_url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, list) and result:
            return result[0].get("translation_text","")
        return None

    def translate_batch(self, texts: list, target: str, source: str = "auto",
                         is_clinical: bool = False) -> list:
        """Translate multiple texts efficiently"""
        return [self.translate(t, target, source, is_clinical) for t in texts]

    def detect_language(self, text: str) -> Dict:
        """Detect the language of input text"""
        if self.providers_available.get("google") and hasattr(self, "_google_key"):
            try:
                url = "https://translation.googleapis.com/language/translate/v2/detect"
                resp = self._requests.post(url, params={"key":self._google_key,"q":text}, timeout=5)
                data = resp.json()
                detected = data["data"]["detections"][0][0]
                code = detected.get("language","en")
                info = LANG_REGISTRY.get(code,{})
                return {"code":code,"name":info.get("name",code),"confidence":detected.get("confidence",0.9)}
            except Exception: pass
        # Fallback: check character scripts
        has_arabic  = any('\u0600' <= c <= '\u06FF' for c in text)
        has_devan   = any('\u0900' <= c <= '\u097F' for c in text)
        has_chinese = any('\u4E00' <= c <= '\u9FFF' for c in text)
        if has_arabic:
            # Urdu vs Arabic heuristic
            urdu_chars = 'ڈڑٹ'
            code = "ur" if any(c in urdu_chars for c in text) else "ar"
            return {"code":code,"name":LANG_REGISTRY[code]["name"],"confidence":0.85}
        if has_devan: return {"code":"hi","name":"Hindi","confidence":0.8}
        if has_chinese: return {"code":"zh","name":"Chinese","confidence":0.85}
        return {"code":"en","name":"English","confidence":0.7}

    def get_stats(self) -> Dict:
        """Return engine statistics"""
        return {
            "providers_available": {k:v for k,v in self.providers_available.items() if v},
            "cache_size": len(self.cache._cache),
            "supported_languages": len(LANG_REGISTRY),
            "version": "1.0.0",
            "engine": "PhoenixTranslator"
        }


# ── FLASK INTEGRATION ─────────────────────────────────────────────────────────
def create_translation_blueprint():
    """Create a Flask Blueprint for the translation engine — plug into any Flask app"""
    from flask import Blueprint, request, jsonify
    bp = Blueprint("translation", __name__)
    translator = PhoenixTranslator()

    @bp.route("/api/v1/translate", methods=["POST"])
    def translate():
        d = request.get_json(silent=True) or {}
        text        = d.get("text","")
        target      = d.get("target_lang") or d.get("target","English")
        source      = d.get("source_lang","auto")
        is_clinical = d.get("is_clinical",False)
        context     = d.get("context","")
        if not text:
            return jsonify({"ok":True,"translated":"","provider":"passthrough","latency_ms":0})
        result = translator.translate(text, target, source, is_clinical, context=context)
        return jsonify({
            "ok": True,
            "translated": result.text,
            "provider": result.provider,
            "latency_ms": result.latency_ms,
            "cached": result.cached,
            "source_lang": result.source_lang,
            "target_lang": result.target_lang,
            "error": result.error
        })

    @bp.route("/api/v1/translate/batch", methods=["POST"])
    def translate_batch():
        d = request.get_json(silent=True) or {}
        texts  = d.get("texts",[])
        target = d.get("target_lang","English")
        source = d.get("source_lang","auto")
        is_clinical = d.get("is_clinical",False)
        if not texts:
            return jsonify({"ok":True,"results":[]})
        results = translator.translate_batch(texts, target, source, is_clinical)
        return jsonify({"ok":True,"results":[{"text":r.text,"provider":r.provider,"latency_ms":r.latency_ms} for r in results]})

    @bp.route("/api/v1/detect", methods=["POST"])
    def detect():
        d = request.get_json(silent=True) or {}
        text = d.get("text","")
        if not text:
            return jsonify({"ok":False,"error":"No text provided"}),400
        result = translator.detect_language(text)
        return jsonify({"ok":True,"detected":result})

    @bp.route("/api/v1/translate/stats", methods=["GET"])
    def stats():
        return jsonify({"ok":True,"stats":translator.get_stats()})

    @bp.route("/api/v1/languages", methods=["GET"])
    def languages():
        langs = [{"code":k,"name":v["name"],"rtl":v["rtl"],"deepl_supported":v.get("deepl_ok",False),"clinical_grade":v.get("clinical",False)} for k,v in LANG_REGISTRY.items()]
        return jsonify({"ok":True,"languages":langs,"total":len(langs)})

    return bp, translator


# ── STANDALONE DEMO ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=" * 60)
    print("PhoenixMinds Universal Translation Engine v1.0")
    print("=" * 60)

    t = PhoenixTranslator()
    print(f"\nAvailable providers: {[k for k,v in t.providers_available.items() if v]}")
    print(f"Supported languages: {len(LANG_REGISTRY)}")
    print()

    # Test translations
    tests = [
        ("Your child has shown significant progress in speech therapy.", "Urdu"),
        ("The IEP goals have been updated for this term.", "Arabic"),
        ("Please confirm medication has been given.", "Hindi"),
        ("Autism Spectrum Disorder evaluation complete.", "French"),
        ("Emergency: please contact your therapist immediately.", "Urdu"),
    ]

    for text, lang in tests:
        print(f"EN → {lang}:")
        print(f"  IN : {text}")
        result = t.translate(text, lang, is_clinical=True)
        print(f"  OUT: {result.text}")
        print(f"  VIA: {result.provider} | {result.latency_ms:.0f}ms")
        print()

    print("Stats:", json.dumps(t.get_stats(), indent=2))
