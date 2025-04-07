"""
Created by: Chris Gambill
Created on: 2025-03-27
Last Edited: 2025-04-07
"""

import streamlit as st
import json
from datetime import datetime
from openai import OpenAI
from azure.storage.blob import BlobServiceClient
import smtplib
from email.mime.text import MIMEText

# --- Setup API keys ---
openai_key = st.secrets.get("OPENAI_API_KEY", "your-openai-key")
client = OpenAI(api_key=openai_key)
st.session_state.score = 0 
azure_conn_str = st.secrets["azure_blob"]["connection_string"]
container_name = st.secrets["azure_blob"]["container_name"]
st.session_state.score = 0 
feedback_summary = ''
def upload_to_azure_blob(data, filename):
    blob_service = BlobServiceClient.from_connection_string(azure_conn_str)
    blob_client = blob_service.get_blob_client(container=container_name, blob=filename)
    blob_client.upload_blob(json.dumps(data, indent=2), overwrite=True)

# --- Initialize session state ---
if "quiz_started" not in st.session_state:
    st.session_state.quiz_started = False
if "quiz_submitted" not in st.session_state:
    st.session_state.quiz_submitted = False

# --- PAGE SETUP ---
st.set_page_config(page_title="Data Engineering Mentee Assessment", layout="centered")
st.title("🧠 Mentee Skill Assessment + Quiz")
st.write("Let's assess your current skills and goals. Then you'll take a short quiz based on your answers!")

# --- SECTION 1: Self-Reflection ---
st.header("Section 1: Self-Reflection")
mentee_name = st.text_input("What is your name?")
mentee_email = st.text_input("What is your email address?")
why_mentor = st.multiselect("Why do you want a mentor?", [
    "To gain technical skills", "To seek career guidance", "To expand my network", "To improve soft skills", "Other"])
short_term_goals = st.multiselect("What are your short-term goals (6–12 months)?", [
    "Secure a job in data engineering", "Improve a specific technical skill", "Gain confidence", "Build a portfolio", "Other"])
long_term_goals = st.multiselect("What are your long-term goals (3–5 years)?", [
    "Become a senior data engineer", "Leadership role", "Start a consultancy", "Grow in current position", "Other"])
feedback_style = st.selectbox("How do you prefer to receive feedback?", [
    "Direct", "Encouraging with constructive criticism", "Step-by-step guidance", "Written", "Other"])
data_interests = st.text_area("What are your interests/passions? This will help us develop a specific project and roadmap.")
# --- SECTION 2: Logistics ---
st.header("Section 2: Expectations & Logistics")
meeting_freq = st.selectbox("How often would you like to meet?", ["Weekly", "Bi-weekly", "Monthly", "As needed"])
communication = st.selectbox("Preferred communication method:", [
    "Video calls", "Phone", "Emails", "Messaging apps", "In-person (if local)"])
mentorship_goal = st.multiselect("What do you hope to achieve by the end of this mentorship?", [
    "Clear career path", "Master specific skills", "Portfolio/project", "Confidence", "Other"])
success_metric = st.multiselect("How will you measure success?", [
    "Achieved goals", "Improved skills/confidence", "Professional relationship", "Career advancement", "Other"])

# --- SECTION 3: Skill Ratings ---
st.header("Section 3: Skill Assessment (Rate 1–5)")
technical_skills = {
    "SQL": st.slider("SQL (Query Writing, Optimization)", 1, 5, 3),
    "Python": st.slider("Python (Data Manipulation, Scripting)", 1, 5, 3),
    "Data Warehousing": st.slider("Data Warehousing Concepts (ETL, Modeling)", 1, 5, 3),
    "Big Data": st.slider("Big Data Technologies (Hadoop, Spark)", 1, 5, 1),
    "Cloud": st.slider("Cloud Platforms (AWS, Azure, GCP)", 1, 5, 2),
    "DB Management": st.slider("Database Management (SQL Server, etc.)", 1, 5, 2),
    "Visualization": st.slider("Visualization Tools (Power BI, Tableau)", 1, 5, 3),
    "Version Control": st.slider("Version Control (Git/GitHub)", 1, 5, 3),
    "Data Quality": st.slider("Data Quality and Validation", 1, 5, 3),
    "APIs": st.slider("APIs and Web Services", 1, 5, 2)
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

# --- SECTION 4: Final Thoughts ---
st.header("Section 4: Final Considerations")
concerns = st.text_area("Any questions or concerns before we begin?")
ready = st.selectbox("Are you ready to proceed?", ["Yes, let's proceed", "No, let's reassess", "Let’s discuss further"])

# --- Generate Quiz ---
if st.button("Submit Self-Assessment"):
    st.success("✅ Assessment submitted. Generating your personalized quiz...")
    skill_summary = "\n".join([f"{k}: {v}/5" for k, v in technical_skills.items()])

    prompt = f"""
You are a professional technical mentor. Based on the following self-rated skills, generate 10 multiple-choice questions (1 correct answer each) to assess their actual skill level. Focus on data engineering topics like SQL, Python, ETL, cloud, data modeling, APIs, and tools like Power BI.
The first option should be a default selection saying 'please select from the below options' so that the correct answer is not the default answer. 
Use a JSON format:
[
  {{
    "question": "What does SELECT * do in SQL?",
    "choices": ["Returns all columns", "Deletes data", "Joins tables", "Updates values"],
    "answer": "Returns all columns"
  }},
  ...
]

Skills:
{skill_summary}
"""

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    project_response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": project_prompt}],
        temperature=0.5
    )

    try:
        st.session_state.questions = json.loads(response.choices[0].message.content)
        st.session_state.quiz_started = True
        st.session_state.quiz_submitted = False
        st.session_state.project = json.loads(project_response.choices[0].message.content)
    except Exception as e:
        st.error("There was a problem generating your quiz.")
        st.stop()

# --- Show Quiz ---
if st.session_state.quiz_started:
    st.header("🎯 Your Personalized Skill Quiz")
    score = 0
    user_answers = []

    for i, q in enumerate(st.session_state.questions):
        user_answer = st.radio(f"{i+1}. {q['question']}", q["choices"], key=f"q_{i}")
        user_answers.append({
            "question": q["question"],
            "your_answer": user_answer,
            "correct_answer": q["answer"]
        })
        if user_answer == q["answer"]:
            score += 1

    if st.button("Submit Quiz"):
        st.session_state.quiz_submitted = True
        st.session_state.user_answers = user_answers
        st.session_state.score = score 
# --- Quiz Results ---
if st.session_state.quiz_submitted:
    st.success(f"🎉 You scored {st.session_state.score} out of {len(st.session_state.questions)}!")

    summary_prompt = f"""
    You are a technical mentor. Based on this quiz score ({st.session_state.score}/{len(st.session_state.questions)}) and the quiz content below, write a short feedback summary (~3-5 sentences) highlighting areas of strength and what the mentee should focus on improving. In addition, for the incorrect answers, please provide the question and correct answer. 
    Quiz:
    {json.dumps(st.session_state.questions, indent=2)}
    """

    summary_response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": summary_prompt}],
        temperature=0.5
    )
    feedback_summary = summary_response.choices[0].message.content
    
    project_prompt = f"""
    You are a professional Data Career Mentor/Coach. Based on the following self-rated skills and passions please create an end-to-end data engineering projct.
    The data-source should be free or low cost and related to the below passion areas. Provide links to direct mentee on where to access data and/or how to request data access. The project should include areas such as extracting data from sources, loading data into a database, cleaning data, modeling data, aggragations, and some visualization in a tool of choice.                  

    Skills:
    {technical_skills}

    Passions: 
    {data_interests}

    Use JSON format: 
    {{
    "Name": {mentee_name},
    "email": {mentee_email},
    "Project_Title": "Provide a project title here"
    "Project_Software_Skill_requirements": "Provide nessissary skills and software needed to perform the tasks"
    "Project_Details": "Provide project details"
    }}
    """
    
    project_response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": project_prompt}],
    temperature=0.5
    )   

    project = project_response.choices[0].message.content
    result = {
        "timestamp": datetime.now().isoformat(),
        "self_assessment": {
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
            "interests": data_interests
        },
        "quiz": st.session_state.user_answers,
        "score": st.session_state.score,
        "feedback_summary": feedback_summary,
        "project_suggestion": project
    }

    filename = f"mentee_result_{mentee_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
    upload_to_azure_blob(result, filename)

    st.write("✅ Results saved to cloud. Here's your personalized feedback:")
    st.markdown(f"**Feedback Summary:**\n\n{feedback_summary}")


def send_followup_email(to_email, mentee_name, score, feedback_summary):
    subject = f"Your Data Engineering Assessment Results – {mentee_name}"
    calendly_link = "https://calendly.com/chris-gambill-gambilldataengineering/data-consulting-initial-meeting"

    body = f"""
Hi {mentee_name},

Thanks for completing the skill assessment! You are a great fit for our mentoring program!

🎯 Your Quiz Score: {score}/10

📋 Feedback Summary:
{feedback_summary}

If you're ready to chat about your data journey or mentorship options, feel free to book a time with me here:
{calendly_link}

Looking forward to connecting!

– Chris Gambill
Gambill Data
chris.gambill@gambilldataengineering.com
    Follow us on LinkedIn https://www.linkedin.com/company/gambill-data
🌐 Visit our website at https://www.gambilldataengineering.com
Check out our YouTube channel https://www.youtube.com/@gambilldataengineering 
            """

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = st.secrets["email"]["sender"]
    msg['To'] = to_email

    try:
        with smtplib.SMTP(st.secrets["email"]["smtp_server"], st.secrets["email"]["smtp_port"]) as server:
            server.starttls()
            server.login(st.secrets["email"]["sender"], st.secrets["email"]["password"])
            server.send_message(msg)
        st.success("📧 Follow-up email sent!")
    except Exception as e:
        st.error(f"❌ Failed to send email: {e}")

send_followup_email(mentee_email, mentee_name, st.session_state.score, feedback_summary)
