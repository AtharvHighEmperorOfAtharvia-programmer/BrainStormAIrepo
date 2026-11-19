# BrainStormAI™ — Streamlit edition (single file)
#
# Run locally:   streamlit run app.py
# Deploy:        push app.py + requirements.txt to GitHub, then deploy on
#                Streamlit Community Cloud (share.streamlit.io)


import streamlit as st
import io
import json
import re
from datetime import datetime
import sys
import subprocess


import streamlit as st
from docx import Document
from openai import OpenAI

# ----------------------------------------------------------------------
# Central configuration
# ----------------------------------------------------------------------
MODEL_NAME = "nvidia/nemotron-3.5-super-vl:free"
MARK_NUMBER = 7
APP_NAME = "BrainStormAI"

SYMBOL = r"""
╔══════════════════════════════════╗
║        B R A I N S T O R M       ║
║              ⚡ 🧠 ⚡           ║
╚══════════════════════════════════╝
"""

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

MENU = [
    "1. Note something on your BrainPad",
    "2. Print your current BrainPad",
    "3. Ask StormBot",
    "4. Save BrainPad as a Word file",
    "5. Debate mode",
    "6. Add permanent context for StormBot chats",
    "7. Finish and save project",
]

st.set_page_config(
    page_title=f"{APP_NAME} Mark {MARK_NUMBER}",
    page_icon="🧠",
    layout="wide",
)


# ----------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------
def init_state():
    defaults = {
        "screen": "home",          # "home" or "project"
        "file_name": "",
        "brain_pad": {},
        "history": [],
        "permacontext": {},        # permanent context sent with every StormBot chat
        "saved": False,
        "pending_reply": None,     # latest StormBot reply awaiting save choice
        "word_bytes": None,
        "debate": None,
        "debate_error": None,
        "debate_notice": None,
        "confirm_exit": False,
        "goodbye": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def start_project(file_name, brain_pad, history, permacontext=None):
    st.session_state.screen = "project"
    st.session_state.file_name = file_name
    st.session_state.brain_pad = brain_pad
    st.session_state.history = history
    st.session_state.permacontext = permacontext or {}
    st.session_state.saved = False
    st.session_state.pending_reply = None
    st.session_state.word_bytes = None
    st.session_state.debate = None
    st.session_state.debate_error = None
    st.session_state.debate_notice = None
    st.session_state.confirm_exit = False
    st.session_state.goodbye = None


def go_home(goodbye=None):
    st.session_state.screen = "home"
    st.session_state.file_name = ""
    st.session_state.brain_pad = {}
    st.session_state.history = []
    st.session_state.permacontext = {}
    st.session_state.saved = False
    st.session_state.pending_reply = None
    st.session_state.word_bytes = None
    st.session_state.debate = None
    st.session_state.debate_error = None
    st.session_state.debate_notice = None
    st.session_state.confirm_exit = False
    st.session_state.goodbye = goodbye


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def next_number(brain_pad, prefix):
    # One more than the highest existing number, so removing an entry (or a
    # legacy file's numbering) can never make a new entry overwrite an old one
    numbers = [
        int(key[len(prefix):]) for key in brain_pad
        if key.startswith(prefix) and key[len(prefix):].isdigit()
    ]
    return max(numbers, default=0) + 1


def format_brain_pad(brain_pad):
    return "\n\n".join(f"{key}: {value}" for key, value in brain_pad.items())


def safe_filename(name):
    cleaned = re.sub(r"[^\w\- ]+", "_", name).strip()
    return cleaned or "project"


def get_client():
    """User-supplied key (sidebar) wins; otherwise fall back to Streamlit secrets."""
    api_key = (st.session_state.get("api_key_input") or "").strip()

    if not api_key:
        try:
            api_key = st.secrets.get("OPENROUTER_API_KEY")
        except Exception:
            api_key = None

    if not api_key:
        return None

    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


def project_json_string():
    project_data = {
        "project_name": st.session_state.file_name,
        "brain_pad": st.session_state.brain_pad,
        "history": st.session_state.history,
        "permanent_context": st.session_state.permacontext,
        "saved_at": datetime.now().astimezone().isoformat(),
    }
    return json.dumps(project_data, indent=4, ensure_ascii=False)


def build_docx_bytes(file_name, brain_pad):
    doc = Document()
    doc.add_heading(file_name, level=1)

    export_time = datetime.now().astimezone().isoformat()
    doc.add_paragraph(f"Date and time of export: {export_time}")

    for key, value in brain_pad.items():
        doc.add_paragraph(f"{key}: {value}")

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def convert_legacy_brain_pad(old_brain_pad):
    """Support older project files that stored BrainPad as a list."""
    brain_pad = {}
    for index, item in enumerate(old_brain_pad, start=1):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            key, value = item
            brain_pad[f"{key} {index}"] = value
        else:
            brain_pad[f"Note {index}"] = item
    return brain_pad


def parse_project(project_data, default_name):
    if isinstance(project_data, dict):
        file_name = project_data.get("project_name", default_name)
        brain_pad = project_data.get("brain_pad", {})
        history = project_data.get("history", [])
        permacontext = project_data.get("permanent_context", {})
    else:
        # Older project files that stored BrainPad as a list
        file_name = default_name
        brain_pad = convert_legacy_brain_pad(project_data)
        history = []
        permacontext = {}

    # Older list-based BrainPads stored inside project dictionaries
    if isinstance(brain_pad, list):
        brain_pad = convert_legacy_brain_pad(brain_pad)

    if not isinstance(brain_pad, dict):
        raise ValueError("BrainPad data is not in a recognised format.")

    # Keep only well-formed history entries
    if not isinstance(history, list):
        history = []
    history = [
        pair for pair in history
        if isinstance(pair, dict) and "user" in pair and "stormbot" in pair
    ]

    # Permanent context: older Colab saves used keys like "Extra context 1:"
    if not isinstance(permacontext, dict):
        permacontext = {}
    permacontext = {
        str(key).rstrip(":"): str(value) for key, value in permacontext.items()
    }

    return file_name, brain_pad, history, permacontext


# ----------------------------------------------------------------------
# AI
# ----------------------------------------------------------------------
def process_input(client, user_input, history, brainpad, permacontext):
    m = [
        {
            "role": "system",
            "content": (
                f"You are StormBot, the AI brainstorming assistant "
                f"for {APP_NAME}. Your purpose is to help users "
                "generate, explore, and develop ideas creatively "
                "while remaining helpful and intellectually honest. "
                "Remember: these are the user's ideas, not yours. "
                "Use the conversation history provided in the "
                "following messages for context.\n\n"
                "Here is some permanent context provided by the user:\n"
                f"{format_brain_pad(permacontext) or 'None'}\n\n"
                f"BrainPad:\n{format_brain_pad(brainpad) or 'Empty'}"
            ),
        }
    ]

    # Include the last ten prompt-reply pairs as conversation context
    for pair in history[-10:]:
        m.append({"role": "user", "content": pair["user"]})
        m.append({"role": "assistant", "content": pair["stormbot"]})

    m.append({"role": "user", "content": user_input})

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=m,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"


def build_debate_prompt(topic, side, ai_side):
    return f"""
You are StormBot, participating in a formal debate.

Topic: {topic}

User's position: {side}
Your position: {ai_side}
Debate till now:
Defend your assigned position using logical reasoning.
Respond directly to the user's arguments.
Do not fabricate facts or statistics.
Remain respectful and acknowledge valid arguments.
Never switch your assigned position.

You are StormBot of BrainStormAI, an assistant
helping users generate and refine ideas.

This debate is intended to explore ideas,
their advantages and disadvantages.

All ideas belong to the user and are refined
through BrainStormAI.
"""


# ----------------------------------------------------------------------
# Callbacks
# ----------------------------------------------------------------------
def mark_saved():
    st.session_state.saved = True


def save_and_exit():
    go_home("Goodbye! Your project file was downloaded.")


def exit_without_saving():
    go_home("Goodbye! Keep thinking, keep writing and keep brainstorming.")


def request_exit():
    if st.session_state.saved:
        go_home("Goodbye!")
    else:
        st.session_state.confirm_exit = True


def cancel_exit():
    st.session_state.confirm_exit = False


def save_pending_reply():
    pending = st.session_state.pending_reply
    if pending and not pending["saved"]:
        brain_pad = st.session_state.brain_pad
        n = next_number(brain_pad, "AI-GENERATED IDEA ")
        brain_pad[f"AI-GENERATED IDEA {n}"] = pending["text"]
        pending["saved"] = True
        st.session_state.saved = False


def save_debate_reply():
    debate = st.session_state.debate
    if debate and debate["last_reply"] and not debate["last_reply_saved"]:
        brain_pad = st.session_state.brain_pad
        n = next_number(brain_pad, "AI-GENERATED IDEA ")
        brain_pad[f"AI-GENERATED IDEA {n}"] = debate["last_reply"]
        debate["last_reply_saved"] = True
        st.session_state.saved = False


def end_debate():
    st.session_state.debate = None
    st.session_state.debate_notice = "Debate concluded."


def remove_context(key):
    st.session_state.permacontext.pop(key, None)
    st.session_state.saved = False


# ----------------------------------------------------------------------
# Home screen
# ----------------------------------------------------------------------
def render_home():
    st.title(f"{APP_NAME}™")
    st.write(
        "Welcome to ThesisCorp's latest project - BrainStormAI. "
        "Here you can guide the untamed power of your mind into "
        "something meaningful, store it for later and process it "
        "again with our chatbot, StormBot."
    )
    st.code(SYMBOL, language=None)

    if st.session_state.goodbye:
        st.success(st.session_state.goodbye)

    # Feature announcement
    with st.container(border=True):
        st.markdown(
            "🆕 **New upgrade: Permanent context for StormBot **  \n"
            "Tell StormBot the things it should always know, such as your "
            "subject, your goals or how you like answers written, and it will "
            "keep them in mind in every chat. Open a project and choose "
            "**Add permanent context for StormBot chats** from the menu. "
            "Your context is saved in your project file, so it's still there "
            "when you upload the project again."
            " History already existed for your conversations, but it was preserved only till the last ten prompt-reply pairs."
        )

    st.info(
        "Your work lives in this browser session. Use **Finish and save "
        "project** to download your project file, and upload it here later "
        "to continue."
    )

    tab_new, tab_load = st.tabs(["Create a new project", "Upload a saved project"])

    with tab_new:
        with st.form("create_form"):
            name = st.text_input("Enter a project name")
            create = st.form_submit_button("Create project")
        if create:
            if name.strip():
                start_project(name.strip(), {}, [])
                st.rerun()
            else:
                st.warning("Please enter a name.")

    with tab_load:
        uploaded = st.file_uploader(
            "Upload a saved project (.brainpad.json)", type=["json"]
        )
        if st.button("Load project", disabled=uploaded is None):
            default_name = re.sub(
                r"(\.brainpad)?\.json$", "", uploaded.name, flags=re.IGNORECASE
            )
            try:
                project_data = json.loads(uploaded.getvalue().decode("utf-8"))
                file_name, brain_pad, history, permacontext = parse_project(
                    project_data, default_name
                )
            except Exception as e:
                st.error(f"Error loading project: {str(e)}")
                st.caption(
                    "Try another file, or create a new project in the first tab."
                )
            else:
                start_project(file_name, brain_pad, history, permacontext)
                st.rerun()


# ----------------------------------------------------------------------
# Project sections
# ----------------------------------------------------------------------
def section_note():
    st.subheader("Note something on your BrainPad")
    with st.form("note_form", clear_on_submit=True):
        note = st.text_area("Enter a note")
        add = st.form_submit_button("Add note")
    if add:
        if note.strip():
            brain_pad = st.session_state.brain_pad
            n = next_number(brain_pad, "Note ")
            brain_pad[f"Note {n}"] = note
            st.session_state.saved = False
            st.success("Note added to BrainPad.")
        else:
            st.warning("Please enter a note.")


def section_view():
    st.subheader("Current BrainPad")
    brain_pad = st.session_state.brain_pad
    if not brain_pad:
        st.info("Your BrainPad is empty.")
        return
    for key, value in brain_pad.items():
        with st.container(border=True):
            st.markdown(f"**{key}**")
            st.markdown(str(value))


def section_ask():
    st.subheader("Ask StormBot")

    context_count = len(st.session_state.permacontext)
    if context_count:
        st.caption(
            f"StormBot is using {context_count} permanent context "
            f"item{'s' if context_count != 1 else ''}."
        )

    with st.form("ask_form", clear_on_submit=True):
        question = st.text_area("Enter your question")
        submitted = st.form_submit_button("Ask StormBot")

    if submitted:
        if not question.strip():
            st.warning("Please enter a question.")
        else:
            client = get_client()
            if client is None:
                st.warning("Add your OpenRouter API key in the sidebar first.")
            else:
                with st.spinner("StormBot is thinking..."):
                    reply = process_input(
                        client,
                        question,
                        st.session_state.history,
                        st.session_state.brain_pad,
                        st.session_state.permacontext,
                    )

                # Store the conversation, keeping only the last ten pairs
                st.session_state.history.append(
                    {"user": question, "stormbot": reply}
                )
                st.session_state.history = st.session_state.history[-10:]
                st.session_state.pending_reply = {
                    "question": question,
                    "text": reply,
                    "saved": False,
                }
                st.session_state.saved = False

    pending = st.session_state.pending_reply
    if pending:
        with st.chat_message("user"):
            st.markdown(pending["question"])
        with st.chat_message("assistant"):
            st.markdown(f"**StormBot:**\n\n{pending['text']}")
        if pending["saved"]:
            st.success("Reply saved to BrainPad.")
        else:
            st.button(
                "Save StormBot's reply to BrainPad",
                on_click=save_pending_reply,
            )


def section_word():
    st.subheader("Save BrainPad as a Word file")
    st.caption(
        "The Word file is generated on demand and downloaded to your device."
    )

    if st.button("Generate Word file"):
        st.session_state.word_bytes = build_docx_bytes(
            st.session_state.file_name, st.session_state.brain_pad
        )

    if st.session_state.word_bytes:
        st.download_button(
            "Download Word file",
            data=st.session_state.word_bytes,
            file_name=f"{safe_filename(st.session_state.file_name)}.docx",
            mime=DOCX_MIME,
        )
        st.caption(
            "Generate again if you've added anything to your BrainPad since."
        )


def section_debate():
    st.subheader("Debate mode")
    st.caption(
        "Have a debate to generate ideas and learn about their "
        "advantages and disadvantages."
    )

    if st.session_state.debate_notice:
        st.info(st.session_state.debate_notice)
        st.session_state.debate_notice = None

    debate = st.session_state.debate

    # ---- Setup ----
    if debate is None:
        with st.form("debate_setup"):
            topic = st.text_input("Enter your debate topic")
            side = st.radio("Enter your side", ["for", "against"], horizontal=True)
            bp = st.radio(
                "Would you like to give StormBot access to your BrainPad?",
                ["y", "n"],
                format_func=lambda v: "Yes" if v == "y" else "No",
                horizontal=True,
            )
            start = st.form_submit_button("Begin debate")

        if start:
            if not topic.strip():
                st.warning("Please enter a debate topic.")
            else:
                topic = topic.strip()
                ai_side = "against" if side == "for" else "for"

                # Include BrainPad context only with permission
                brainpad_context = (
                    format_brain_pad(st.session_state.brain_pad)
                    if bp == "y"
                    else "No BrainPad access granted."
                )

                messages = [
                    {
                        "role": "system",
                        "content": build_debate_prompt(topic, side, ai_side),
                    },
                    {
                        "role": "user",
                        "content": f"""
Relevant BrainPad context:
{brainpad_context}

The debate is beginning.
Present your opening argument.
""",
                    },
                ]

                st.session_state.debate = {
                    "topic": topic,
                    "side": side,
                    "ai_side": ai_side,
                    "messages": messages,
                    "d_history": [],
                    "last_reply": None,
                    "last_reply_saved": False,
                }
                st.session_state.debate_error = None
                st.rerun()
        return

    # ---- Active debate ----
    st.markdown(
        f"**Topic:** {debate['topic']}  \n"
        f"**You:** {debate['side']} · **StormBot:** {debate['ai_side']}"
    )
    st.markdown("--- DEBATE BEGINS ---")

    # Transcript (skip the system prompt and the context message)
    for m in debate["messages"][2:]:
        if m["role"] == "user":
            with st.chat_message("user"):
                st.markdown(m["content"])
        else:
            with st.chat_message("assistant"):
                st.markdown(f"**StormBot ({debate['ai_side']}):**\n\n{m['content']}")

    if st.session_state.debate_error:
        st.error(st.session_state.debate_error)
        st.session_state.debate_error = None

    # Option to save AI reply to BrainPad
    if debate["last_reply"]:
        if debate["last_reply_saved"]:
            st.success("StormBot's reply has been saved to BrainPad.")
        else:
            st.button(
                "Save StormBot's reply to BrainPad",
                on_click=save_debate_reply,
            )

    with st.form("debate_turn", clear_on_submit=True):
        argument = st.text_area("Your argument")
        save_human = st.checkbox("Save my argument to BrainPad")
        send = st.form_submit_button("Send argument")

    if send:
        argument = argument.strip()
        if not argument:
            st.warning("Please enter an argument.")
        else:
            client = get_client()
            if client is None:
                st.warning("Add your OpenRouter API key in the sidebar first.")
            else:
                # Option to save human argument to BrainPad
                if save_human:
                    brain_pad = st.session_state.brain_pad
                    n = next_number(brain_pad, "Note ")
                    brain_pad[f"Note {n}"] = argument
                    st.session_state.saved = False

                debate["messages"].append({"role": "user", "content": argument})

                try:
                    with st.spinner("StormBot is responding..."):
                        response = client.chat.completions.create(
                            model=MODEL_NAME,
                            messages=debate["messages"],
                        )
                    reply = response.choices[0].message.content

                    if not reply:
                        debate["messages"].pop()
                        st.session_state.debate_error = (
                            "StormBot returned an empty response. "
                            "Please send your argument again."
                        )
                    else:
                        reply = reply.strip()
                        debate["d_history"].append(
                            {"user": argument, "stormbot": reply}
                        )
                        debate["d_history"] = debate["d_history"][-10:]
                        debate["messages"].append(
                            {"role": "assistant", "content": reply}
                        )
                        debate["last_reply"] = reply
                        debate["last_reply_saved"] = False

                except Exception as e:
                    debate["messages"].pop()
                    st.session_state.debate_error = (
                        f"Debate error: {e}. Please send your argument again."
                    )

                st.rerun()

    st.button("End debate", on_click=end_debate)


def section_context():
    st.subheader("Add permanent context for StormBot chats")
    st.caption(
        "StormBot keeps this in mind in every chat. "
        "Make sure it is free from any ambiguity."
    )

    with st.form("context_form", clear_on_submit=True):
        context = st.text_area("Enter the context")
        add = st.form_submit_button("Add context")
    if add:
        if context.strip():
            permacontext = st.session_state.permacontext
            n = next_number(permacontext, "Extra context ")
            permacontext[f"Extra context {n}"] = context.strip()
            st.session_state.saved = False
            st.success("Context added. StormBot will use it in every chat.")
        else:
            st.warning("Please enter some context.")

    permacontext = st.session_state.permacontext
    if not permacontext:
        st.info("No permanent context yet.")
        return
    for key, value in list(permacontext.items()):
        with st.container(border=True):
            st.markdown(f"**{key}**")
            st.markdown(value)
            st.button(
                "Remove",
                key=f"remove_{key}",
                on_click=remove_context,
                args=(key,),
            )


def section_save():
    st.subheader("Finish and save project")
    st.write(
        "Download your project file to keep it. Upload it from the home "
        "screen later to pick up where you left off."
    )
    st.download_button(
        "Download project file",
        data=project_json_string(),
        file_name=f"{safe_filename(st.session_state.file_name)}.brainpad.json",
        mime="application/json",
        on_click=mark_saved,
    )
    if st.session_state.saved:
        st.success("Project saved.")


# ----------------------------------------------------------------------
# Sidebar + project screen
# ----------------------------------------------------------------------
def render_sidebar():
    with st.sidebar:
        st.markdown(f"### 🧠 {APP_NAME}™")
        st.caption(f"Mark {MARK_NUMBER}")

        st.text_input(
            "OpenRouter API key",
            type="password",
            key="api_key_input",
            help=(
                "Used only for this browser session and never stored. "
                "Get a free key at openrouter.ai."
            ),
        )
        if get_client() is None:
            st.warning("Enter your OpenRouter API key to use StormBot.")

        if st.session_state.screen == "project":
            st.divider()
            st.radio("Menu", MENU, key="menu")
            st.divider()
            st.button("Exit project", on_click=request_exit)


def render_project():
    st.title(f"{APP_NAME}™ — BrainPad")
    st.caption(f"Project: {st.session_state.file_name}")
    if not st.session_state.saved:
        st.caption("● Unsaved changes")

    if st.session_state.confirm_exit:
        st.warning("You have unsaved changes.")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button(
                "Save project & exit",
                data=project_json_string(),
                file_name=(
                    f"{safe_filename(st.session_state.file_name)}.brainpad.json"
                ),
                mime="application/json",
                on_click=save_and_exit,
            )
        with col2:
            st.button("Exit without saving", on_click=exit_without_saving)
        with col3:
            st.button("Cancel", on_click=cancel_exit)
        st.divider()

    choice = st.session_state.get("menu", MENU[0])

    if choice == MENU[0]:
        section_note()
    elif choice == MENU[1]:
        section_view()
    elif choice == MENU[2]:
        section_ask()
    elif choice == MENU[3]:
        section_word()
    elif choice == MENU[4]:
        section_debate()
    elif choice == MENU[5]:
        section_context()
    elif choice == MENU[6]:
        section_save()


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    init_state()
    render_sidebar()

    if st.session_state.screen == "home":
        render_home()
    else:
        render_project()


main()
