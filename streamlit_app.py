import json
import re
import time
from datetime import date, timedelta

import requests
import streamlit as st
from pypdf import PdfReader

st.set_page_config(page_title="StudyMate AI", page_icon="🎓", layout="wide")

# ---------- AI ----------
MODELS = [
    st.secrets.get("GEMINI_MODEL", "gemini-flash-lite-latest"),
    "gemini-flash-latest",
    "gemini-3.8-flash",
]
SYSTEM = (
    "You are StudyMate, a friendly, clear tutor for students. Explain simply with a short "
    "example. Keep answers under 150 words. If a document is provided, answer only from it "
    "and say so if the answer is not there."
)


def gemini(prompt, system=None, max_tokens=500):
    key = st.secrets.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing in secrets.")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.6},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    last = ""
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            try:
                r = requests.post(url, params={"key": key}, json=body, timeout=25)
            except requests.RequestException as e:
                last = f"Network error: {e}"
                break
            if r.status_code == 200:
                try:
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    last = "Empty answer."
                    break
            last = f"Gemini error {r.status_code} on {model}"
            if r.status_code in (429, 500, 503) and attempt == 0:
                time.sleep(0.7)
                continue
            break
    raise RuntimeError("The AI is busy right now. Please try again. (" + last + ")")


# ---------- State ----------
ss = st.session_state
defaults = {
    "page": "Home", "chat": [], "pdf_text": "", "pdf_info": None, "pdf_chat": [],
    "quiz": None, "qi": 0, "score": 0, "answered": False, "topic": "General",
    "scores": [], "hours": 0, "plan": [],
}
for k, v in defaults.items():
    ss.setdefault(k, v)

PAGES = ["Home", "AI Tutor", "Study Materials", "Quiz", "Study Planner", "Progress"]

BANK = [
    {"q": "Which organelle produces most of a cell's energy?", "o": ["Nucleus", "Mitochondrion", "Ribosome", "Golgi body"], "a": 1},
    {"q": "What is the value of 7 × 8?", "o": ["54", "56", "58", "64"], "a": 1},
    {"q": "Which gas do plants absorb for photosynthesis?", "o": ["Oxygen", "Nitrogen", "Carbon dioxide", "Hydrogen"], "a": 2},
    {"q": "What is the SI unit of force?", "o": ["Joule", "Watt", "Pascal", "Newton"], "a": 3},
    {"q": "Who wrote the play Romeo and Juliet?", "o": ["Charles Dickens", "William Shakespeare", "Jane Austen", "Mark Twain"], "a": 1},
]


def goto(page):
    ss.page = page


st.sidebar.title("🎓 StudyMate AI")
st.sidebar.radio("Go to", PAGES, key="page")


# ---------- Pages ----------
def home():
    st.title("Your Personal AI Study Companion")
    st.write("Ask questions, learn from your own PDFs, test yourself with quizzes and plan your study week, all in one place.")
    st.button("Start Learning", type="primary", on_click=goto, args=("AI Tutor",))
    st.divider()
    cards = [
        ("💬 AI Tutor", "Chat with a tutor that explains things step by step.", "AI Tutor"),
        ("📄 Study Materials", "Upload a PDF and ask questions about it.", "Study Materials"),
        ("🧠 Quiz", "One question at a time with instant feedback.", "Quiz"),
        ("🗓️ Study Planner", "Turn your exam date into a day-by-day plan.", "Study Planner"),
        ("📈 Progress", "See scores, study hours and completed quizzes.", "Progress"),
    ]
    cols = st.columns(len(cards))
    for col, (title, text, page) in zip(cols, cards):
        with col.container(border=True):
            st.subheader(title)
            st.caption(text)
            st.button("Open", key="open_" + page, on_click=goto, args=(page,))


def show_chat(history):
    for role, text in history:
        with st.chat_message(role):
            st.write(text)


def tutor():
    st.header("AI Tutor")
    st.caption("Ask anything you are stuck on. Your tutor answers like a friendly teacher.")
    if not ss.chat:
        ss.chat.append(("assistant", "Hi! I'm your StudyMate tutor. What are you studying today?"))
    show_chat(ss.chat)
    q = st.chat_input("Type your question, e.g. What is Newton's second law?")
    if q:
        ss.chat.append(("user", q))
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    a = gemini(q, SYSTEM)
                except Exception as e:
                    a = str(e)
            st.write(a)
        ss.chat.append(("assistant", a))


def materials():
    st.header("Study Materials")
    st.caption("Upload a PDF, then ask questions about what is inside.")
    f = st.file_uploader("Drag and drop your PDF here", type="pdf")
    if f is not None and (ss.pdf_info is None or ss.pdf_info["name"] != f.name):
        try:
            reader = PdfReader(f)
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:40])
            ss.pdf_text = text
            ss.pdf_info = {
                "name": f.name, "size": f"{max(1, f.size // 1024)} KB",
                "pages": len(reader.pages), "words": len(text.split()),
            }
            ss.pdf_chat = [("assistant", "Your PDF is ready. Ask me anything about it.")]
        except Exception:
            ss.pdf_info = None
            st.error("Could not read this PDF. Try another file.")
    if ss.pdf_info:
        i = ss.pdf_info
        with st.container(border=True):
            st.subheader("📕 " + i["name"])
            c1, c2, c3 = st.columns(3)
            c1.metric("Size", i["size"])
            c2.metric("Pages", i["pages"])
            c3.metric("Words read", f"{i['words']:,}")
        show_chat(ss.pdf_chat)
        q = st.chat_input("Ask about this PDF, e.g. Summarise chapter 2")
        if q:
            ss.pdf_chat.append(("user", q))
            with st.chat_message("user"):
                st.write(q)
            with st.chat_message("assistant"):
                with st.spinner("Reading..."):
                    try:
                        if not ss.pdf_text.strip():
                            a = "I couldn't find readable text in this PDF. It may be a scan."
                        else:
                            a = gemini(f"DOCUMENT:\n{ss.pdf_text[:12000]}\n\nQUESTION: {q}", SYSTEM)
                    except Exception as e:
                        a = str(e)
                st.write(a)
            ss.pdf_chat.append(("assistant", a))


def start_quiz(questions, topic):
    ss.quiz, ss.qi, ss.score, ss.answered, ss.topic = questions, 0, 0, False, topic


def quiz():
    st.header("Quiz")
    st.caption("Pick a topic and answer one question at a time.")
    if ss.quiz is None:
        topic = st.text_input("Topic", placeholder="e.g. Cell biology")
        c1, c2 = st.columns(2)
        if c1.button("Generate with AI", type="primary"):
            if not topic.strip():
                st.warning("Enter a topic first.")
            else:
                with st.spinner("Writing your questions..."):
                    try:
                        raw = gemini(
                            f'Create 5 multiple-choice questions for a student on "{topic[:120]}". '
                            'Return only JSON: an array of {"q": string, "o": [4 strings], "a": index of the correct option 0-3}.',
                            max_tokens=1500,
                        )
                        m = re.search(r"\[.*\]", raw, re.DOTALL)
                        qs = json.loads(m.group(0) if m else raw)
                        ok = isinstance(qs, list) and qs and all(
                            isinstance(x, dict) and x.get("q") and isinstance(x.get("o"), list)
                            and len(x["o"]) == 4 and isinstance(x.get("a"), int) and 0 <= x["a"] <= 3
                            for x in qs
                        )
                        if not ok:
                            raise ValueError("Bad quiz format. Click Generate again.")
                        start_quiz(qs[:5], topic)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not create the quiz: {e}")
        if c2.button("Use sample quiz"):
            start_quiz(BANK, "General knowledge")
            st.rerun()
        return

    Q, i = ss.quiz, ss.qi
    if i >= len(Q):
        pct = round(ss.score / len(Q) * 100)
        with st.container(border=True):
            st.title(f"{ss.score}/{len(Q)}")
            st.subheader("Great work!" if pct >= 80 else "Good effort, keep going." if pct >= 50 else "Review the topic and try again.")
            st.caption(f"{pct}% on {ss.topic}")
        c1, c2 = st.columns(2)
        if c1.button("Take another quiz"):
            ss.quiz = None
            st.rerun()
        c2.button("View progress", on_click=goto, args=("Progress",))
        return

    q = Q[i]
    st.progress(i / len(Q), text=f"Question {i + 1} of {len(Q)}  |  Score {ss.score}")
    choice = st.radio(q["q"], q["o"], index=None, key=f"r{i}", disabled=ss.answered)
    if not ss.answered:
        if st.button("Submit answer", type="primary", disabled=choice is None):
            ss.answered = True
            if q["o"].index(choice) == q["a"]:
                ss.score += 1
            st.rerun()
    else:
        if q["o"].index(choice) == q["a"]:
            st.success("Correct!")
        else:
            st.error(f"Not quite. The answer is: {q['o'][q['a']]}")
        if st.button("Next question" if i + 1 < len(Q) else "See result", type="primary"):
            ss.qi += 1
            ss.answered = False
            if ss.qi >= len(Q):
                ss.scores.append({"topic": ss.topic, "score": round(ss.score / len(Q) * 100)})
            st.rerun()


STEPS = ["Read and note key ideas", "Practise problems", "Recap with flashcards", "Take a mock quiz", "Fix weak spots", "Final revision"]


def planner():
    st.header("Study Planner")
    st.caption("Tell us what to study and when. We split the hours into daily sessions.")
    with st.form("plan"):
        c1, c2 = st.columns(2)
        subject = c1.text_input("Subject", placeholder="Chemistry")
        topic = c2.text_input("Topic", placeholder="Organic reactions")
        c3, c4 = st.columns(2)
        exam = c3.date_input("Exam date", value=date.today() + timedelta(days=7), min_value=date.today() + timedelta(days=1))
        hours = c4.number_input("Study hours (total)", 1, 200, 6)
        go = st.form_submit_button("Generate Plan", type="primary")
    if go:
        if not subject.strip() or not topic.strip():
            st.warning("Fill in subject and topic.")
        else:
            n = min((exam - date.today()).days, 14)
            per = max(0.5, round(hours / n * 2) / 2)
            ss.plan = []
            for i in range(n):
                d = date.today() + timedelta(days=i + 1)
                tasks = [STEPS[5], "Rest and sleep well"] if i == n - 1 else [STEPS[i % 4], STEPS[(i + 1) % 4]]
                ss.plan.append((d.strftime("%a, %d %b"), f"{subject}: {topic}", per, tasks))
            ss.hours += hours
    if ss.plan:
        cols = st.columns(3)
        for idx, (d, label, per, tasks) in enumerate(ss.plan):
            with cols[idx % 3].container(border=True):
                st.subheader(d)
                st.caption(label)
                st.write(f"**{per} hr{'' if per == 1 else 's'}**")
                for t in tasks:
                    st.write("• " + t)


def progress():
    st.header("Progress")
    st.caption("Your numbers update as you take quizzes and plan study time.")
    s = ss.scores
    avg = round(sum(x["score"] for x in s) / len(s)) if s else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Average quiz score", f"{avg}%")
    c2.metric("Study hours planned", ss.hours)
    c3.metric("Completed quizzes", len(s))
    st.subheader("Weekly goal (10 hours)")
    st.progress(min(ss.hours / 10, 1.0), text=f"{min(round(ss.hours / 10 * 100), 100)}% of your weekly goal")
    st.subheader("Recent quiz scores")
    if s:
        st.bar_chart({f"{i + 1}. {x['topic']}": x["score"] for i, x in enumerate(s[-7:])})
    else:
        st.info("Take a quiz to see your scores here.")
    if st.button("Reset progress"):
        ss.scores, ss.hours, ss.plan = [], 0, []
        st.rerun()


{"Home": home, "AI Tutor": tutor, "Study Materials": materials, "Quiz": quiz,
 "Study Planner": planner, "Progress": progress}[ss.page]()