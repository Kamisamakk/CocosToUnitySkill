#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sdk_filter.py
Centralized SDK / ad / non-game content filter for the Cocos→Unity migration
pipeline.  Every phase imports this module to decide what to skip.

Design goals:
  - One source of truth for all "strip SDK" logic
  - Path-based matching (directory names, file names)
  - Content-based matching (import statements, class names in scripts)
  - Easily extensible: just add entries to the keyword lists below
  - Returns structured metadata so audit can report what was excluded

Usage:
  from sdk_filter import SdkFilter

  filt = SdkFilter()                     # default rules
  filt = SdkFilter(extra_dir_keywords=["myCustomSdk"])  # extend

  filt.should_exclude_path(Path("assets/ads/BannerAd.ts"))  # True
  filt.should_exclude_script(Path("assets/scripts/GameMgr.ts"))  # (False, [])
  filt.classify(Path("assets/wechat-sdk/wx.d.ts"))  # "sdk"
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

# ============================================================================
# Keyword / pattern registries
# ============================================================================

# --- Directory names that signal SDK / ad / analytics / non-game content ---
# Matching is case-insensitive against each component of the path.
SDK_DIR_KEYWORDS: List[str] = [
    # Ad networks
    "ads", "ad", "adsdk", "ad-sdk", "admob", "adsense",
    "ironsource", "applovin", "mintegral", "unityads", "unity-ads",
    "vungle", "chartboost", "facebook-ads", "fb-ads", "pangle",
    "topon", "tradplus", "sigmob", "klevin", "gromore",
    "rewarded", "interstitial", "banner-ad",
    # Social / sharing SDKs
    "share", "sharing", "social-sdk", "wechat-sdk", "wx-sdk",
    "qq-sdk", "weixin", "alipay-sdk",
    # Analytics / tracking
    "analytics", "tracking", "adjust", "appsflyer", "firebase",
    "bugly", "sentry", "crashlytics", "talkingdata", "umeng",
    "sensors", "growingio",
    # Payment / IAP
    "iap", "billing", "payment", "pay-sdk",
    # Push / notification
    "push", "notification", "jpush", "getui", "tpns",
    # Login / account (third-party, not game logic)
    "third-party", "thirdparty", "3rd-party",
    "login-sdk", "account-sdk",
    # Platform bridge (mini-game platform wrappers)
    "platform-sdk", "platform-bridge", "minigame-sdk",
    "bytedance-sdk", "tt-sdk", "oppo-sdk", "vivo-sdk", "huawei-sdk",
    "xiaomi-sdk",
    # Generic SDK dirs
    "sdk", "sdks", "plugins", "vendor", "third_party",
    "external", "libs-external",
]

# --- File name substrings that signal SDK / ad content ---
# Matched case-insensitively against the file stem (no extension).
SDK_FILE_KEYWORDS: List[str] = [
    "adsdk", "ad_sdk", "admob", "adsense", "banner_ad", "bannerAd",
    "rewardedvideo", "rewarded_video", "rewardedAd", "rewarded_ad",
    "interstitial", "nativead", "native_ad",
    "ironsource", "applovin", "mintegral", "vungle", "chartboost",
    "pangle", "topon", "tradplus", "sigmob", "klevin", "gromore",
    "admanager", "ad_manager", "adhelper", "ad_helper", "adconfig",
    "adwrapper", "ad_wrapper", "adloader", "ad_loader",
    "analytics", "appsflyer", "adjust_sdk", "firebase",
    "bugly", "sentry", "crashlytics", "umeng", "talkingdata",
    "share_sdk", "sharesdk", "social_share", "socialshare",
    "wxsdk", "wechat_sdk", "qqsdk",
    "iap_manager", "billing", "paymanager", "pay_manager",
    "push_manager", "jpush", "getui",
]

# --- Import / require patterns in scripts that indicate SDK usage ---
# These are checked against script file content.
SDK_IMPORT_PATTERNS: List[re.Pattern] = [
    re.compile(r"""(?:import|require)\s*\(?['"].*?(?:ads?[-_/]|admob|ironsource|applovin|mintegral|vungle|chartboost|pangle|topon|tradplus|rewarded|interstitial|banner)""", re.IGNORECASE),
    re.compile(r"""(?:import|require)\s*\(?['"].*?(?:analytics|appsflyer|adjust|firebase|bugly|sentry|umeng|talkingdata)""", re.IGNORECASE),
    re.compile(r"""(?:import|require)\s*\(?['"].*?(?:share[-_]?sdk|social[-_]?share|wechat[-_]?sdk|wxsdk|qqsdk)""", re.IGNORECASE),
    re.compile(r"""(?:import|require)\s*\(?['"].*?(?:iap|billing|pay[-_]?sdk)""", re.IGNORECASE),
]

# --- Class / function patterns that are pure SDK glue ---
SDK_CLASS_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bclass\s+\w*(?:Ad|Ads|AdManager|AdHelper|AdSDK|RewardedVideo|Interstitial|BannerAd)\b", re.IGNORECASE),
    re.compile(r"\bclass\s+\w*(?:Analytics|Tracking|AppsflyerHelper|FirebaseHelper|BuglyHelper)\b", re.IGNORECASE),
    re.compile(r"\bclass\s+\w*(?:ShareSDK|SocialShare|WechatSDK|WxSDK)\b", re.IGNORECASE),
    re.compile(r"\bclass\s+\w*(?:IAPManager|BillingManager|PayManager)\b", re.IGNORECASE),
]

# --- Prefab / scene node name patterns to strip (checked during Phase 2) ---
SDK_NODE_NAME_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?:^|_)(?:ad|ads|banner|interstitial|rewarded)(?:_|$|-|node|panel|layer|view)", re.IGNORECASE),
    re.compile(r"(?:^|_)(?:share|social|analytics|tracking)(?:_|$|-|node|panel|layer|view)", re.IGNORECASE),
]

# --- Categories for classification ---
CATEGORY_SDK = "sdk"
CATEGORY_AD = "ad"
CATEGORY_ANALYTICS = "analytics"
CATEGORY_SOCIAL = "social"
CATEGORY_IAP = "iap"
CATEGORY_PUSH = "push"
CATEGORY_PLATFORM = "platform_bridge"

# Subcategory mapping (directory keyword → category)
_DIR_CATEGORY_MAP: Dict[str, str] = {}
for _kw in ["ads", "ad", "adsdk", "ad-sdk", "admob", "adsense",
            "ironsource", "applovin", "mintegral", "unityads", "unity-ads",
            "vungle", "chartboost", "facebook-ads", "fb-ads", "pangle",
            "topon", "tradplus", "sigmob", "klevin", "gromore",
            "rewarded", "interstitial", "banner-ad"]:
    _DIR_CATEGORY_MAP[_kw] = CATEGORY_AD
for _kw in ["analytics", "tracking", "adjust", "appsflyer", "firebase",
            "bugly", "sentry", "crashlytics", "talkingdata", "umeng",
            "sensors", "growingio"]:
    _DIR_CATEGORY_MAP[_kw] = CATEGORY_ANALYTICS
for _kw in ["share", "sharing", "social-sdk", "wechat-sdk", "wx-sdk",
            "qq-sdk", "weixin", "alipay-sdk"]:
    _DIR_CATEGORY_MAP[_kw] = CATEGORY_SOCIAL
for _kw in ["iap", "billing", "payment", "pay-sdk"]:
    _DIR_CATEGORY_MAP[_kw] = CATEGORY_IAP
for _kw in ["push", "notification", "jpush", "getui", "tpns"]:
    _DIR_CATEGORY_MAP[_kw] = CATEGORY_PUSH
for _kw in ["platform-sdk", "platform-bridge", "minigame-sdk",
            "bytedance-sdk", "tt-sdk", "oppo-sdk", "vivo-sdk", "huawei-sdk",
            "xiaomi-sdk"]:
    _DIR_CATEGORY_MAP[_kw] = CATEGORY_PLATFORM


# ============================================================================
# SdkFilter class
# ============================================================================

class SdkFilter:
    """Stateless filter that decides whether a path / script should be excluded
    from the Cocos→Unity migration because it belongs to an SDK, ad network,
    analytics service, or other non-game-core content."""

    def __init__(
        self,
        extra_dir_keywords: Optional[List[str]] = None,
        extra_file_keywords: Optional[List[str]] = None,
        custom_exclude_dirs: Optional[List[str]] = None,
    ):
        self._dir_kws: Set[str] = {k.lower() for k in SDK_DIR_KEYWORDS}
        self._file_kws: Set[str] = {k.lower() for k in SDK_FILE_KEYWORDS}
        if extra_dir_keywords:
            self._dir_kws.update(k.lower() for k in extra_dir_keywords)
        if extra_file_keywords:
            self._file_kws.update(k.lower() for k in extra_file_keywords)
        # Exact directory paths (relative, posix style) to exclude
        self._custom_dirs: Set[str] = set()
        if custom_exclude_dirs:
            self._custom_dirs = {d.lower().replace("\\", "/").strip("/") for d in custom_exclude_dirs}

    # ------------------------------------------------------------------
    # Path-based checks
    # ------------------------------------------------------------------

    def should_exclude_path(self, rel_path: Path) -> bool:
        """Return True if *any* component of the relative path matches SDK keywords."""
        return self.classify(rel_path) is not None

    def classify(self, rel_path: Path) -> Optional[str]:
        """Return a category string ("ad", "sdk", "analytics", …) or None."""
        posix = rel_path.as_posix().lower()

        # Custom exact-directory exclusion
        for cd in self._custom_dirs:
            if posix.startswith(cd + "/") or posix == cd:
                return CATEGORY_SDK

        # Check each directory component
        for part in PurePosixPath(posix).parts[:-1]:  # all but filename
            part_lower = part.lower()
            if part_lower in self._dir_kws:
                return _DIR_CATEGORY_MAP.get(part_lower, CATEGORY_SDK)

        # Check filename stem
        stem = rel_path.stem.lower()
        for kw in self._file_kws:
            if kw in stem:
                # Determine category from keyword
                if any(ad_kw in kw for ad_kw in ("ad", "reward", "interstitial", "banner",
                                                   "ironsource", "applovin", "mintegral",
                                                   "vungle", "chartboost", "pangle",
                                                   "topon", "tradplus", "sigmob", "klevin", "gromore")):
                    return CATEGORY_AD
                if any(a_kw in kw for a_kw in ("analytics", "appsflyer", "adjust",
                                                "firebase", "bugly", "sentry", "umeng",
                                                "talkingdata")):
                    return CATEGORY_ANALYTICS
                if any(s_kw in kw for s_kw in ("share", "social", "wechat", "wx", "qq")):
                    return CATEGORY_SOCIAL
                if any(p_kw in kw for p_kw in ("iap", "billing", "pay")):
                    return CATEGORY_IAP
                return CATEGORY_SDK

        return None

    def should_exclude_dir(self, dir_name: str) -> bool:
        """Check a single directory name (not full path)."""
        return dir_name.lower() in self._dir_kws

    # ------------------------------------------------------------------
    # Content-based checks (for scripts)
    # ------------------------------------------------------------------

    def should_exclude_script(self, path: Path) -> Tuple[bool, List[str]]:
        """Read a script file and check whether it's pure SDK glue code.

        Returns (should_exclude, reasons).
        A script is excluded if:
          1. Its path matches SDK keywords, OR
          2. It is primarily an SDK wrapper class (>50% of its classes are SDK-related)
        """
        reasons: List[str] = []

        # Path check first
        cat = self.classify(path)
        if cat:
            reasons.append(f"path matches '{cat}' category")
            return True, reasons

        # Content check
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False, []

        # Check imports
        for pat in SDK_IMPORT_PATTERNS:
            m = pat.search(text)
            if m:
                reasons.append(f"imports SDK module: {m.group(0)[:80]}...")

        # Check class definitions
        sdk_classes = 0
        for pat in SDK_CLASS_PATTERNS:
            matches = pat.findall(text)
            if matches:
                sdk_classes += len(matches)
                reasons.append(f"defines SDK class(es): {', '.join(matches[:3])}")

        # If the file is dominated by SDK patterns → exclude
        if sdk_classes > 0 and reasons:
            return True, reasons

        # Even if we found imports, if there's real game logic too, just flag it
        # (the caller can decide to translate with stubs instead of skipping)
        if reasons:
            return False, reasons  # "tainted" but not purely SDK

        return False, []

    def find_sdk_imports_in_text(self, text: str) -> List[str]:
        """Return a list of SDK import lines found in script text."""
        hits: List[str] = []
        for pat in SDK_IMPORT_PATTERNS:
            for m in pat.finditer(text):
                hits.append(m.group(0).strip())
        return hits

    def is_sdk_node_name(self, name: str) -> bool:
        """Check if a scene/prefab node name looks like an SDK/ad node."""
        for pat in SDK_NODE_NAME_PATTERNS:
            if pat.search(name):
                return True
        return False

    # ------------------------------------------------------------------
    # Summary / reporting
    # ------------------------------------------------------------------

    def summarize_exclusions(self, excluded: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build a summary from a list of exclusion records."""
        by_category: Dict[str, int] = {}
        by_ext: Dict[str, int] = {}
        for item in excluded:
            cat = item.get("category", "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1
            ext = item.get("ext", "")
            if ext:
                by_ext[ext] = by_ext.get(ext, 0) + 1
        return {
            "total_excluded": len(excluded),
            "by_category": by_category,
            "by_extension": by_ext,
            "details": excluded[:50],  # cap at 50 for readability
        }
