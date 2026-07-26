"""
updater.py
----------
نظام تحديث تلقائي وآمن للوكيل:
  - يتحقق من وجود نسخة أحدث على GitHub (بقراءة ملف VERSION.txt من الريبو).
  - إذا وُجد تحديث، يطبّقه فقط بموافقتك (git pull) — لا يوجد أي تعديل
    تلقائي للكود من الذكاء الاصطناعي نفسه، والتحديث الوحيد الممكن هو
    سحب كود جديد كتبه أنت (أو راجعته) ورفعته على GitHub بنفسك.

للتفعيل، لازم:
  1. تنشئ ريبو خاص بك على GitHub وترفع له مجلد المشروع كامل.
  2. تعبي GITHUB_REPO بالأسفل بصيغة "اسم_المستخدم/اسم_الريبو".
  3. تستنسخ المشروع (git clone) من نفس الريبو بدل نسخ الملفات يدويًا،
     حتى يصير المجلد مربوط فعليًا بـ git ويقدر يسحب تحديثات.
"""

import os
import subprocess

import requests

GITHUB_REPO = "arkankut30-ctrl/personal-agent"
GITHUB_BRANCH = "main"

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(PROJECT_DIR, "VERSION.txt")


def get_local_version() -> str:
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "0.0.0"


def check_for_update() -> dict:
    """
    يرجع dict فيه:
      available: bool - هل يوجد تحديث
      local_version / remote_version: str
      message: str - رسالة مفهومة للواجهة
    """
    local_version = get_local_version()

    if not GITHUB_REPO:
        return {
            "available": False,
            "local_version": local_version,
            "remote_version": None,
            "message": "لم يتم ربط المشروع بريبو GitHub بعد. راجع updater.py و README.",
        }

    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/VERSION.txt"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        remote_version = r.text.strip()
    except Exception as e:
        return {
            "available": False,
            "local_version": local_version,
            "remote_version": None,
            "message": f"تعذر الاتصال بـ GitHub: {e}",
        }

    if remote_version and remote_version != local_version:
        return {
            "available": True,
            "local_version": local_version,
            "remote_version": remote_version,
            "message": f"يوجد تحديث جديد ({remote_version}) — النسخة الحالية: {local_version}",
        }

    return {
        "available": False,
        "local_version": local_version,
        "remote_version": remote_version,
        "message": "أنت تستخدم آخر نسخة متوفرة.",
    }


def apply_update() -> dict:
    """ينفذ git pull لتحديث الكود من الريبو. يتطلب أن يكون المجلد git repo فعليًا."""
    if not os.path.isdir(os.path.join(PROJECT_DIR, ".git")):
        return {
            "success": False,
            "message": (
                "هذا المجلد غير مرتبط بـ git. لتفعيل التحديث التلقائي، "
                "استنسخ المشروع بأمر git clone من ريبوك على GitHub بدل نقل الملفات يدويًا."
            ),
        }

    try:
        result = subprocess.run(
            ["git", "pull", "origin", GITHUB_BRANCH],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {"success": False, "message": f"فشل التحديث: {result.stderr.strip()}"}
        return {
            "success": True,
            "message": (result.stdout.strip() or "تم التحديث بنجاح.")
            + " — أعد تشغيل البرنامج لتطبيق التحديث.",
        }
    except Exception as e:
        return {"success": False, "message": f"خطأ أثناء التحديث: {e}"}
