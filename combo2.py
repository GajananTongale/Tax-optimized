import os
import json
import re
import streamlit as st
from dotenv import load_dotenv
from langchain.tools import YouTubeSearchTool
from pymongo import MongoClient
from datetime import datetime
import pandas as pd
import plotly.express as px
from gtts import gTTS


# Load environment variables
load_dotenv()

# Load workflow data
with open('ITR3.json', 'r', encoding='utf-8') as f:
    workflow_data = json.load(f)

# Initialize components
tool = YouTubeSearchTool()
client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("DB_NAME", "tax_assistant")]
appointments = db[os.getenv("COLLECTION_NAME", "appointments")]

# Configure session states
if 'expert_contact' not in st.session_state:
    st.session_state.expert_contact = {}
if 'current_step' not in st.session_state:
    st.session_state.current_step = None
if 'current_service' not in st.session_state:
    st.session_state.current_service = None

# Streamlit config
st.set_page_config(page_title="TaxPro Assistant", layout="wide", page_icon="📊")

# Professional CSS styling
st.markdown("""
<style>
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        border: 1px solid #4B56D2;
        color: white;
        background-color: #4B56D2;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #3A44B2;
        color: white;
    }
    .bot-response {
        background-color: #ffffff;
        border-radius: 10px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border: 1px solid #e0e0e0;
        color:black;
    }
    .service-card {
        background: white;
        padding: 2rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin: 1rem 0;
    }
    .sidebar .sidebar-content {
        background-color: #ffffff;
    }
</style>
""", unsafe_allow_html=True)

TAX_RULES = {
    "HRA": {
        "condition": lambda data: data["rent_paid"] > 0 and not data["hra_claimed"],
        "suggestion": lambda _: "Claim HRA exemption using rent receipts",
        "limit": "Actual HRA received, rent paid minus 10% of salary, or 50%/40%/30% of salary (metro/non-metro)"
    },
    "80C": {
        "condition": lambda data: data["investment_80c"] < 150000,
        "suggestion": lambda
            data: f"Invest ₹{150000 - data['investment_80c']} more in LIC/PPF/ELSS for full 80C benefit",
        "limit": "₹1.5 lakh"
    },
    "80D": {
        "condition": lambda data: data["health_insurance"] == 0,
        "suggestion": lambda _: "Buy health insurance to claim up to ₹25,000 deduction",
        "limit": "₹25,000 (₹50,000 for seniors)"
    },
    "87A": {
        "condition": lambda data: data["taxable_income"] <= 1200000,
        "suggestion": lambda _: "You qualify for Section 87A rebate - ₹12,500 tax relief!",
        "limit": "Taxable income ≤ ₹12L"
    }
}
TAX_GLOSSARY = {
    "80C": {
        "description": "Invest in savings plans & pay less tax!",
        "example": "Invest ₹1.5L in LIC, PPF, or ELSS to reduce taxable income",
        "limit": "₹1.5 lakh deduction"
    },
    "HRA": {
        "description": "Tax benefit for paying rent!",
        "example": "Claim deduction by submitting rent receipts to your employer",
        "limit": "Minimum of: Actual HRA, Rent paid - 10% salary, or 50%/40% salary (metro/non-metro)"
    },
    "TDS": {
        "description": "Tax Deducted at Source - prepaid tax by employer",
        "example": "₹5K deducted from ₹60K salary as advance tax payment",
        "limit": "As per income tax slabs"
    },
    "Section 87A": {
        "description": "Rebate for income under ₹12L",
        "example": "If taxable income is ₹10L, pay ₹0 tax!",
        "limit": "Available for incomes ≤ ₹12L"
    }
}


def get_category_data(category_id):
    return next(
        (cat for cat in workflow_data['categories'] if cat['category_id'] == category_id),
        None
    )

def text_to_speech(text, lang='en'):
    """Convert text to speech and return audio file"""
    tts = gTTS(text=text, lang=lang, slow=False)
    filename = f"tts_{hash(text)}.mp3"
    tts.save(filename)
    return filename
def display_step(step):
    col1, col2 = st.columns([3, 1])

    with col1:
        with st.container():
            st.markdown(f"""
            <div class='styled-container'>
                <h3 style="color: #2A76B3; margin-bottom: 1.5rem;">📋 {step.get('subject', 'ITR Filing Assistance')}</h3>
                <div class="styled-input">
                    {step['bot_response']}
                </div>
            """, unsafe_allow_html=True)

            # Text-to-speech button
            if st.button('🔊 Read Aloud', key=f"tts_{step['step_id']}",
                         help="Listen to this step's instructions",
                         type="secondary"):
                audio_file = text_to_speech(step['bot_response'])
                st.audio(audio_file, format='audio/mp3')
                os.remove(audio_file)  # Clean up temporary file

            if 'resources' in step:
                st.markdown("---")
                st.markdown("**📌 Helpful Resources:**")
                for link in step['resources'].get('links', []):
                    st.markdown(f"- [{link['title']}]({link['link']})")

            st.markdown("</div>", unsafe_allow_html=True)

            # Step navigation buttons
            if 'user_options' in step:
                cols = st.columns(len(step['user_options']))
                for idx, option in enumerate(step['user_options']):
                    with cols[idx]:
                        if st.button(option['option_text'],
                                     key=f"step_{step['step_id']}_option_{idx}",
                                     on_click=lambda n=option['next_step_id']: st.session_state.update(
                                         {'current_step': n})):
                            pass

    with col2:
        if 'metadata' in step and 'video_query' in step['metadata']:
            try:
                results = tool.run(f"{step['metadata']['video_query']} India 2024")
                if results:
                    # Extract video ID using regex
                    video_id = re.search(r"v=([a-zA-Z0-9_-]+)", results).group(1)
                    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/0.jpg"

                    st.markdown(f"""
                        <a href="https://www.youtube.com/watch?v={video_id}" target="_blank">
                            <img src="{thumbnail_url}" style="width:100%; border-radius:10px;">
                        </a>
                        """, unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Error loading video: {str(e)}")
def expert_consultation():
    with st.form("expert_form", clear_on_submit=True):
        st.subheader("Schedule Expert Consultation")
        cols = st.columns(2)
        with cols[0]:
            st.session_state.expert_contact['name'] = st.text_input("Full Name")
            st.session_state.expert_contact['email'] = st.text_input("Email Address")
        with cols[1]:
            st.session_state.expert_contact['date'] = st.date_input("Preferred Date")
            st.session_state.expert_contact['time'] = st.time_input("Preferred Time")

        if st.form_submit_button("Schedule Consultation"):
            appointment = {
                **st.session_state.expert_contact,
                "datetime": datetime.combine(
                    st.session_state.expert_contact['date'],
                    st.session_state.expert_contact['time']
                ),
                "status": "Pending"
            }
            appointments.insert_one(appointment)
            st.success("Consultation scheduled successfully! Our expert will contact you shortly.")


def tax_optimization_module():
    st.title(" Tax Guru - Smart Savings Assistant")
    st.subheader("Your AI-Powered Tax Optimization Companion")

    with st.form("tax_info"):
        col1, col2, col3 = st.columns(3)
        with col1:
            income = st.number_input(" Annual Income (₹)", min_value=0)
            rent_paid = st.number_input(" Annual Rent Paid (₹)", min_value=0)
        with col2:
            investment_80c = st.number_input(" 80C Investments (₹)", min_value=0)
            health_insurance = st.number_input("🩺 Health Insurance Premium (₹)", min_value=0)
        with col3:
            hra_claimed = st.checkbox("Already claiming HRA")
            st.markdown("### Tax Slabs (FY 2023-24)")
            st.markdown("""
                - ₹0-3L: 0%  
                - ₹3-6L: 5%  
                - ₹6-9L: 10%  
                - ₹9-12L: 15%  
                - Above ₹12L: 30%
                """)

        submitted = st.form_submit_button(" Optimize My Taxes", use_container_width=True)

    if submitted:
        user_data = {
            "taxable_income": income,
            "rent_paid": rent_paid,
            "hra_claimed": hra_claimed,
            "investment_80c": investment_80c,
            "health_insurance": health_insurance
        }

        suggestions = []
        for section, rule in TAX_RULES.items():
            if rule["condition"](user_data):
                suggestion_text = rule["suggestion"](user_data)
                suggestions.append((section, suggestion_text, rule['limit']))

        if suggestions:
            st.success("##  Tax Optimization Opportunities")
            cols = st.columns(2)
            with cols[0]:
                for section, text, limit in suggestions:
                    st.markdown(f"""
                        <div style="padding:15px;background-color:#2d2d2d;border-radius:10px;margin:10px 0">
                            <h4> {section}</h4>
                            <p>{text}</p>
                            <small> Limit: {limit}</small>
                        </div>
                        """, unsafe_allow_html=True)
            with cols[1]:
                tax_data = pd.DataFrame({
                    "Category": ["80C Investments", "Health Insurance", "HRA", "Remaining Taxable"],
                    "Amount": [investment_80c, health_insurance, rent_paid,
                               income - (investment_80c + health_insurance + rent_paid)]
                })
                fig = px.pie(tax_data, names="Category", values="Amount",
                             title=" Current Tax Breakdown",
                             color_discrete_sequence=px.colors.sequential.RdBu)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(" Great job! You're maximizing basic tax-saving options.")

def main():
    st.title("Professional Tax Assistance Suite")

    # Service selection buttons
    cols = st.columns(3)
    with cols[0]:
        if st.button("📄 Start ITR Filing", use_container_width=True):
            st.session_state.current_service = "itr"
            st.session_state.current_step = "step_1"
    with cols[1]:
        if st.button("📈 Tax Optimization", use_container_width=True):
            st.session_state.current_service = "optimization"
    with cols[2]:
        if st.button("👨💼 Expert Consultation", use_container_width=True):
            st.session_state.current_service = "expert"

    # Service content display
    if st.session_state.current_service == "itr":
        category_data = get_category_data("tax_filing")
        if category_data:
            current_workflow = category_data['workflows'][0]
            current_step = next(
                (step for step in current_workflow['steps']
                 if step['step_id'] == st.session_state.current_step),
                None
            )
            if current_step:
                display_step(current_step)
            else:
                st.error("Invalid workflow configuration")

    elif st.session_state.current_service == "optimization":
        with st.container():
            st.markdown("<div class='service-card'>", unsafe_allow_html=True)
            tax_optimization_module()
            st.markdown("</div>", unsafe_allow_html=True)

    elif st.session_state.current_service == "expert":
        with st.container():
            st.markdown("<div class='service-card'>", unsafe_allow_html=True)
            expert_consultation()
            st.markdown("</div>", unsafe_allow_html=True)

    # Always show exit option
    if st.session_state.current_service:
        if st.button("← Return to Main Menu"):
            st.session_state.current_service = None
            st.session_state.current_step = None
            st.rerun()


if __name__ == "__main__":
    main()