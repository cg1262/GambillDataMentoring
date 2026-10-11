"""
Mentee Skill Assessment + Quiz
Created by: Chris Gambill
Created on: 2025-03-27
Refactored: 2026-10-06

Flow (one stage per rerun, driven by st.session_state.stage):
  assessment  -> form; on submit, snapshot answers and generate the quiz
  quiz        -> form; on submit, score and move on
  results     -> compute feedback / project / upload / email exactly once,
                 then just display from session_state on every later rerun

The starter-project prompt depends only on the self-assessment, so it is
generated in a background thread while the mentee takes the quiz.

Requires streamlit >= 1.31 (st.radio(index=None), st.write_stream).

.streamlit/secrets.toml:
  OPENAI_API_KEY = "sk-..."
  OPENAI_MODEL = "gpt-4o"            # optional, defaults below

  [azure_blob]
  connection_string = "DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
  container_name = "mentee-results"

  [email]
  sender = "you@yourdomain.com"
  password = "app-password"
  smtp_server = "smtp.gmail.com"
  smtp_port = 587
"""

import json
import random
import re
import smtplib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.mime.text import MIMEText

import streamlit as st
from azure.storage.blob import BlobServiceClient, ContentSettings
from openai import OpenAI

# ---------------------------------------------------------------------------
# Config and clients
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Data Engineering Mentee Assessment", layout="centered")

OPENAI_MODEL = st.secrets.get("OPENAI_MODEL", "gpt-6-luna")
CALENDLY_LINK = "https://calendly.com/chris-gambill-gambilldataengineering/coaching-program-discussion"
QUIZ_LENGTH = 20


@st.cache_resource
def get_openai_client() -> OpenAI:
    # No silent fallback: a missing key should fail here, loudly, not on the first call.
    # The SDK default timeout is 10 minutes; a mentee won't wait that long.
    return OpenAI(api_key=st.secrets["OPENAI_API_KEY"], timeout=90, max_retries=2)


@st.cache_resource
def get_blob_service() -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(st.secrets["azure_blob"]["connection_string"])


@st.cache_resource
def get_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=4)


# Resolved on the script thread so background jobs never touch st.* themselves.
client = get_openai_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def chat(prompt: str, json_mode: bool = False, temperature: float = 0.5) -> str:
    """Single-turn completion. json_mode forces a parseable JSON object back."""
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        **kwargs,
    )
    return response.choices[0].message.content


def chat_stream(prompt: str, temperature: float = 0.5):
    """Same as chat(), but yields text deltas for st.write_stream."""
    stream = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def upload_to_azure_blob(data: dict, filename: str) -> None:
    blob_client = get_blob_service().get_blob_client(
        container=st.secrets["azure_blob"]["container_name"], blob=filename
    )
    blob_client.upload_blob(
        json.dumps(data, indent=2),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )


def send_followup_email(to_email: str, mentee_name: str, score: int, total: int,
                        feedback_summary: str, project: str) -> None:
    cfg = st.secrets["email"]
    subject = f"Your Data Engineering Assessment Results - {mentee_name}"
    body = f"""Hi {mentee_name},

Thanks for completing the skill assessment. Here is a summary of how it went and what I'd suggest focusing on next.

Quiz score: {score}/{total}

Feedback:
{feedback_summary}

Suggested starter project:
{project}

If you'd like to talk through your results and what the mentorship could look like, grab a time here:
{CALENDLY_LINK}

Looking forward to connecting.

Chris Gambill
Gambill Data
chris.gambill@gambilldataengineering.com
LinkedIn: https://www.linkedin.com/company/gambill-data
Website: https://www.gambilldataengineering.com
YouTube: https://www.youtube.com/@gambilldataengineering
"""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    msg["To"] = to_email

    with smtplib.SMTP(cfg["smtp_server"], int(cfg["smtp_port"]), timeout=30) as server:
        server.starttls()
        server.login(cfg["sender"], cfg["password"])
        server.send_message(msg)


def safe_filename_part(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower() or "unknown"


def is_valid_email(text: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text))


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def quiz_prompt(technical_skills: dict) -> str:
    skill_summary = "\n".join(f"- {k}: {v}/5" for k, v in technical_skills.items())
    return f"""You are a senior data engineering mentor writing a diagnostic quiz.

The candidate self-rated these skills from 1 (none) to 5 (expert):
{skill_summary}

Write exactly {QUIZ_LENGTH} multiple-choice questions following these rules:
- Cover all skill areas from the list above. Weight toward areas
  rated 3 or higher, since those are the claims worth testing, but include at least 2
  questions from each area.
- Match difficulty to the rating: a 4 or 5 earns a question a working senior
  engineer would have to think about; a 2 earns a fundamentals question.
- Each question has exactly 4 choices and exactly one correct answer.
- The "answer" value must match one of the choices exactly, character for character.
- Vary the position of the correct answer across questions.
- Do not use "all of the above" or "none of the above".
- Test judgment and understanding, not trivia or syntax memorization.
- The "topic" value must be one of the skill names from the list above.

Return only JSON in this shape:
{{"questions": [
  {{"topic": "SQL", "difficulty": 4,
    "question": "...", "choices": ["...", "...", "...", "..."],
    "answer": "..."}}
]}}"""


def feedback_prompt(user_answers: list, score: int, total: int) -> str:
    return f"""You are a senior data engineering mentor reviewing a mentee's diagnostic quiz.

Score: {score}/{total}

Each item below has the topic, difficulty, the question, the mentee's answer, and the correct answer:
{json.dumps(user_answers, indent=2)}

Write feedback in markdown with these sections:
1. **Strengths**: topics where the mentee answered correctly, especially at higher difficulty. Two or three sentences.
2. **Focus areas**: topics with incorrect answers, ordered by how foundational they are. Two or three sentences, concrete about what to study.
3. **Questions to review**: for each incorrect answer only, one bullet with the question, what they chose, the correct answer, and one sentence on why.

Keep it direct and encouraging. Do not pad. If every answer was correct, say so and suggest what a harder follow-up would cover."""


def project_prompt(technical_skills: dict, interests: str) -> str:
    skill_summary = "\n".join(f"- {k}: {v}/5" for k, v in technical_skills.items())
    return f"""You are a data engineering career coach designing a portfolio project for a mentee.

Self-rated skills (1 to 5):
{skill_summary}

Interests and passions, in their words:
{interests or "Not provided. Pick a broadly interesting public dataset."}

Design one end-to-end data engineering project that fits those interests and stretches
the skills rated 3 or lower without being out of reach. Use a free or low-cost data
source and link directly to it (or explain how to request access). The project must
cover: extracting data from the source, loading it into a database or lakehouse,
cleaning, modeling (dimensional or otherwise, say which and why), aggregations, and
a visualization layer in a tool of the mentee's choice.

Return markdown with these headings:
## Project title
## Data source (with links)
## Skills and software required
## Project phases (numbered, each with a concrete deliverable)
## Stretch goals"""


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "stage" not in st.session_state:
    st.session_state.stage = "assessment"
    st.session_state.assessment = None
    st.session_state.questions = None
    st.session_state.user_answers = None
    st.session_state.score = 0


def restart() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.title("Mentee Skill Assessment + Quiz")

# ---- Stage 1: self-assessment ------------------------------------------------
if st.session_state.stage == "assessment":
    st.write("Let's assess your current skills and goals. Then you'll take a short quiz based on your answers.")

    with st.form("assessment_form"):
        st.header("Section 1: Self-Reflection")
        mentee_name = st.text_input("What is your name?")
        mentee_email = st.text_input("What is your email address?")
        why_mentor = st.multiselect("Why do you want a mentor?", [
            "To gain technical skills", "To seek career guidance", "To expand my network",
            "To improve soft skills", "Other"])
        short_term_goals = st.multiselect("What are your short-term goals (6 to 12 months)?", [
            "Secure a job in data engineering", "Improve a specific technical skill",
            "Gain confidence", "Build a portfolio", "Other"])
        long_term_goals = st.multiselect("What are your long-term goals (3 to 5 years)?", [
            "Become a senior data engineer", "Leadership role", "Start a consultancy",
            "Grow in current position", "Other"])
        feedback_style = st.selectbox("How do you prefer to receive feedback?", [
            "Direct", "Encouraging with constructive criticism", "Step-by-step guidance",
            "Written", "Other"])
        data_interests = st.text_area(
            "What are your interests/passions? This helps us design a project and roadmap around them.")

        st.header("Section 2: Expectations & Logistics")
        meeting_freq = st.selectbox("How often would you like to meet?",
                                    ["Weekly", "Bi-weekly", "Monthly", "As needed"])
        communication = st.selectbox("Preferred communication method:", [
            "Video calls", "Phone", "Emails", "Messaging apps", "In-person (if local)"])
        mentorship_goal = st.multiselect("What do you hope to achieve by the end of this mentorship?", [
            "Clear career path", "Master specific skills", "Portfolio/project", "Confidence", "Other"])
        success_metric = st.multiselect("How will you measure success?", [
            "Achieved goals", "Improved skills/confidence", "Professional relationship",
            "Career advancement", "Other"])

        st.header("Section 3: Skill Assessment (Rate 1 to 5)")
        technical_skills = {
            "SQL": st.slider("SQL (Query Writing, Optimization)", 1, 5, 3),
            "Python": st.slider("Python (Data Manipulation, Scripting)", 1, 5, 3),
            "Data Warehousing": st.slider("Data Warehousing Concepts (ETL, Modeling)", 1, 5, 3),
            "Big Data": st.slider("Big Data Technologies (Spark, Databricks)", 1, 5, 1),
            "Cloud": st.slider("Cloud Platforms (AWS, Azure, GCP)", 1, 5, 2),
            "DB Management": st.slider("Database Management (SQL Server, etc.)", 1, 5, 2),
            "Visualization": st.slider("Visualization Tools (Power BI, Tableau)", 1, 5, 3),
            "Version Control": st.slider("Version Control (Git/GitHub)", 1, 5, 3),
            "Data Quality": st.slider("Data Quality and Validation", 1, 5, 3),
            "APIs": st.slider("APIs and Web Services", 1, 5, 2),
        }
        soft_skills = {
            "Problem Solving": st.slider("Problem-Solving", 1, 5, 3),
            "Communication": st.slider("Communication Skills", 1, 5, 3),
            "Collaboration": st.slider("Collaboration", 1, 5, 3),
            "Time Management": st.slider("Time Management", 1, 5, 3),
            "Adaptability": st.slider("Adaptability", 1, 5, 3),
            "Project Management": st.slider("Project Management", 1, 5, 3),
            "Attention to Detail": st.slider("Attention to Detail", 1, 5, 3),
            "Mentorship": st.slider("Mentorship (if applicable)", 1, 5, 1),
            "Leadership": st.slider("Leadership (if applicable)", 1, 5, 1),
            "Critical Thinking": st.slider("Critical Thinking", 1, 5, 3),
        }

        st.header("Section 4: Final Considerations")
        concerns = st.text_area("Any questions or concerns before we begin?")
        ready = st.selectbox("Are you ready to proceed?",
                             ["Yes, let's proceed", "No, let's reassess", "Let's discuss further"])

        submitted = st.form_submit_button("Submit Self-Assessment")

    if submitted:
        mentee_name = mentee_name.strip()
        mentee_email = mentee_email.strip()
        if not mentee_name:
            st.error("Please enter your name.")
            st.stop()
        if not is_valid_email(mentee_email):
            st.error("Please enter a valid email address.")
            st.stop()

        st.session_state.assessment = {
            "name": mentee_name,
            "email": mentee_email,
            "why_mentor": why_mentor,
            "short_term_goals": short_term_goals,
            "long_term_goals": long_term_goals,
            "feedback_style": feedback_style,
            "meeting_freq": meeting_freq,
            "communication": communication,
            "mentorship_goal": mentorship_goal,
            "success_metric": success_metric,
            "technical_skills": technical_skills,
            "soft_skills": soft_skills,
            "concerns": concerns,
            "ready": ready,
            "interests": data_interests,
        }

        # Start the project suggestion now; it will be ready by the time the quiz is done.
        st.session_state.project_future = get_executor().submit(
            chat, project_prompt(technical_skills, data_interests), temperature=0.7)

        with st.spinner("Generating your personalized quiz..."):
            try:
                raw = chat(quiz_prompt(technical_skills), json_mode=True)
                questions = json.loads(raw)["questions"]
                # Basic shape validation so a malformed question can't crash the quiz page.
                questions = [
                    q for q in questions
                    if isinstance(q.get("choices"), list) and len(set(q["choices"])) == 4
                    and q.get("answer") in q["choices"] and q.get("question")
                ][:QUIZ_LENGTH]
                if len(questions) < 5:
                    raise ValueError("The model returned too few usable questions.")
                # Models cluster the correct answer in one slot; shuffle so position carries no signal.
                for q in questions:
                    random.shuffle(q["choices"])
            except Exception as e:
                print(f"Quiz generation failed: {e!r}")
                # TODO: drop the error detail once the model call is working again.
                st.error(f"There was a problem generating your quiz ({type(e).__name__}: {e}). "
                         "Please try submitting again.")
                st.stop()

        st.session_state.questions = questions
        st.session_state.stage = "quiz"
        st.rerun()

# ---- Stage 2: quiz ----------------------------------------------------------
elif st.session_state.stage == "quiz":
    st.header("Your Personalized Skill Quiz")
    st.caption(f"{len(st.session_state.questions)} questions. Answer every question before submitting.")

    with st.form("quiz_form"):
        selections = []
        for i, q in enumerate(st.session_state.questions):
            selections.append(st.radio(f"{i + 1}. {q['question']}", q["choices"], index=None, key=f"q_{i}"))
        quiz_submitted = st.form_submit_button("Submit Quiz")

    if quiz_submitted:
        if any(s is None for s in selections):
            st.error("Please answer every question before submitting.")
            st.stop()

        user_answers = []
        score = 0
        for q, chosen in zip(st.session_state.questions, selections):
            correct = chosen == q["answer"]
            score += int(correct)
            user_answers.append({
                "topic": q.get("topic"),
                "difficulty": q.get("difficulty"),
                "question": q["question"],
                "your_answer": chosen,
                "correct_answer": q["answer"],
                "correct": correct,
            })

        st.session_state.user_answers = user_answers
        st.session_state.score = score
        st.session_state.stage = "results"
        st.rerun()

# ---- Stage 3: results -------------------------------------------------------
elif st.session_state.stage == "results":
    a = st.session_state.assessment
    total = len(st.session_state.questions)
    score = st.session_state.score
    # Side effects (API spend, blob write, email) happen only while this is None.
    r = st.session_state.get("results")

    st.success(f"You scored {score} out of {total}.")

    st.subheader("Feedback")
    if r:
        feedback_summary = r["feedback_summary"]
        st.markdown(feedback_summary)
    else:
        try:
            feedback_summary = st.write_stream(
                chat_stream(feedback_prompt(st.session_state.user_answers, score, total)))
        except Exception:
            st.error("There was a problem generating your feedback.")
            st.button("Try again")
            st.stop()

    st.subheader("Suggested starter project")
    if r:
        project = r["project_suggestion"]
    else:
        with st.spinner("Finishing your project suggestion..."):
            try:
                project = st.session_state.project_future.result()
            except Exception:
                try:
                    project = chat(project_prompt(a["technical_skills"], a["interests"]), temperature=0.7)
                except Exception:
                    st.error("There was a problem generating your project suggestion.")
                    st.button("Try again")
                    st.stop()
    st.markdown(project)

    st.markdown(f"Ready to talk through your results? [Book a time with Chris]({CALENDLY_LINK}).")

    if not r:
        r = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": OPENAI_MODEL,
            "self_assessment": a,
            "quiz": st.session_state.user_answers,
            "score": score,
            "total": total,
            "feedback_summary": feedback_summary,
            "project_suggestion": project,
        }
        # Store first so a failure below never causes a regeneration on the next rerun.
        st.session_state.results = r
        st.session_state.upload_status = None
        st.session_state.email_status = None

        # Runs after the results are already on screen, so the mentee isn't waiting on it.
        with st.spinner("Saving your results and sending your email..."):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            filename = f"mentee_result_{safe_filename_part(a['name'])}_{stamp}.json"
            try:
                upload_to_azure_blob(r, filename)
                st.session_state.upload_status = "Results saved."
            except Exception as e:
                print(f"Blob upload failed for {filename}: {e!r}")
                st.session_state.upload_status = "Saving your results failed; Chris has been notified in the logs."

            try:
                send_followup_email(a["email"], a["name"], score, total, feedback_summary, project)
                st.session_state.email_status = f"Results emailed to {a['email']}"
            except Exception as e:
                print(f"Email to {a['email']} failed: {e!r}")
                # TODO: drop the error detail once email is working again.
                st.session_state.email_status = (
                    f"Email failed to send ({type(e).__name__}: {e}). Please save this page for your records.")

    for status in (st.session_state.upload_status, st.session_state.email_status):
        if status and "failed" in status.lower():
            st.warning(status)
        elif status:
            st.caption(status)

    st.button("Start over", on_click=restart)
