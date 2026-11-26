# BrainStormAI™ — Streamlit edition (converted from Colab Mark 9)
import io
import json
from datetime import datetime

import streamlit as st
from docx import Document
from openai import OpenAI

# ---------------------------------------------------------------- config
APP_NAME = "BrainStormAI"
MARK_NUMBER = 9
MODEL_NAME = "nvidia/nemotron-3.5-super-vl:free"

st.set_page_config(page_title=f"{APP_NAME}™", page_icon="🧠", layout="wide")


# ---------------------------------------------------------------- state
def init_state():
    defaults = {
        "project_name": "My Project",
        "brain_pad": {},
        "history": [],          # [{"user": ..., "stormbot": ...}]
        "permacontext": {},
        "dirty": False,
        "wild_reply": None,
        "debate": None,         # dict while a debate is active
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


def mark_dirty():
    st.session_state.dirty = True


def mark_saved():
    st.session_state.dirty = False


def next_key(pad, prefix):
    n = 1
    while f"{prefix} {n}" in pad:
        n += 1
    return f"{prefix} {n}"


def format_brain_pad(pad):
    return "\n\n".join(f"{k}: {v}" for k, v in pad.items())


def add_to_pad(prefix, text):
    st.session_state.brain_pad[next_key(st.session_state.brain_pad, prefix)] = text
    mark_dirty()
    st.toast("Saved to BrainPad ✅")


def reset_project(name="My Project"):
    """Only call from a callback (before widgets are created) or before they exist."""
    st.session_state.project_name = name
    st.session_state.brain_pad = {}
    st.session_state.history = []
    st.session_state.permacontext = {}
    st.session_state.wild_reply = None
    st.session_state.debate = None
    st.session_state.dirty = False
    st.session_state.pop("wild_sel", None)
    for k in [k for k in st.session_state.keys() if str(k).startswith("edit_")]:
        del st.session_state[k]


# ---------------------------------------------------------------- AI
def get_api_key():
    try:
        key = st.secrets.get("OPENROUTER_API_KEY")
    except Exception:
        key = None
    return key or st.session_state.get("user_api_key")


def call_llm(messages):
    """Returns reply text, or None on failure (errors never enter history/BrainPad)."""
    key = get_api_key()
    if not key:
        st.error("No OpenRouter API key found. Add one in the sidebar.")
        return None
    try:
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)
        response = client.chat.completions.create(model=MODEL_NAME, messages=messages)
        reply = response.choices[0].message.content
        if not reply:
            st.warning("StormBot returned an empty response. Please try again.")
            return None
        return reply.strip()
    except Exception as e:
        st.error(f"StormBot encountered an error: {e}")
        return None


def chat_system_prompt():
    permanent = format_brain_pad(st.session_state.permacontext) or "None"
    pad = format_brain_pad(st.session_state.brain_pad) or "Empty"
    return (
        f"You are StormBot, the AI brainstorming assistant for {APP_NAME}. "
        "Your purpose is to help users generate, explore, and develop ideas "
        "creatively while remaining helpful and intellectually honest. "
        "Remember: these are the user's ideas, not yours. "
        "Use the conversation history provided in the following messages for context.\n\n"
        f"Here is some permanent context provided by the user:\n{permanent}\n\n"
        f"BrainPad:\n{pad}"
    )


# ---------------------------------------------------------------- export / import
def build_docx_bytes():
    doc = Document()
    doc.add_heading(st.session_state.project_name or "BrainPad", level=1)
    doc.add_paragraph(
        f"Date and time of export: {datetime.now().astimezone().isoformat()}"
    )
    for key, value in st.session_state.brain_pad.items():
        doc.add_paragraph(f"{key}: {value}")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_json_text():
    return json.dumps(
        {
            "project_name": st.session_state.project_name,
            "brain_pad": st.session_state.brain_pad,
            "history": st.session_state.history[-10:],
            "permanent_context": st.session_state.permacontext,
            "saved_at": datetime.now().astimezone().isoformat(),
        },
        indent=4,
        ensure_ascii=False,
    )


def convert_old_pad(items):
    pad = {}
    for i, item in enumerate(items, start=1):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            pad[f"{item[0]} {i}"] = item[1]
        else:
            pad[f"Note {i}"] = item
    return pad


def load_project_data(data, fallback_name):
    if isinstance(data, dict):
        name = data.get("project_name", fallback_name) or fallback_name
        pad = data.get("brain_pad", {})
        history = data.get("history", [])
        permanent = data.get("permanent_context", {})
    else:  # very old saves stored the BrainPad as a list
        name, pad, history, permanent = fallback_name, data, [], {}

    if isinstance(pad, list):
        pad = convert_old_pad(pad)
    if not isinstance(pad, dict):
        pad = {}
    pad = {str(k): str(v) for k, v in pad.items()}

    if not isinstance(history, list):
        history = []
    history = [
        h for h in history
        if isinstance(h, dict) and "user" in h and "stormbot" in h
    ]

    if not isinstance(permanent, dict):
        permanent = {}
    # Older saves stored keys like "Extra context 1:"
    permanent = {str(k).rstrip(":"): str(v) for k, v in permanent.items()}

    reset_project(str(name))
    st.session_state.brain_pad = pad
    st.session_state.history = history[-10:]
    st.session_state.permacontext = permanent


# Callbacks run before widgets are created, so they can safely set
# widget-bound keys such as project_name.
def do_load():
    up = st.session_state.get("upload_json")
    if up is None:
        return
    try:
        up.seek(0)
        data = json.load(up)
        load_project_data(
            data, up.name.replace(".brainpad.json", "").replace(".json", "")
        )
        st.session_state.load_msg = (
            "success",
            f"Loaded '{st.session_state.project_name}'.",
        )
    except Exception as e:
        st.session_state.load_msg = ("error", f"Error loading project: {e}")


def do_new():
    reset_project()
    st.session_state.load_msg = ("success", "Started a new project.")


# ---------------------------------------------------------------- main
st.title("⚡🧠⚡ BrainStormAI™")
st.caption(
    "Guide the untamed power of your mind into something meaningful, store it "
    "for later and process it again with StormBot."
)

tabs = st.tabs(
    [
        "📝 BrainPad",
        "💬 Ask StormBot",
        "⚡ Wild Ideas",
        "🥊 Debate",
        "📌 Permanent Context",
        "📄 Export",
        "ℹ️ About",
    ]
)

# ---- BrainPad
with tabs[0]:
    st.subheader("Your BrainPad")
    with st.form("note_form", clear_on_submit=True):
        note = st.text_area("Note something", height=100)
        add_note = st.form_submit_button("Add note")
    if add_note:
        if note.strip():
            add_to_pad("Note", note.strip())
        else:
            st.warning("Please enter a note first.")

    pad = st.session_state.brain_pad
    if not pad:
        st.info("Your BrainPad is empty. Add a note above or save a StormBot reply.")
    for key in list(pad.keys()):
        with st.expander(key):
            ekey = f"edit_{key}"
            if ekey not in st.session_state:
                st.session_state[ekey] = pad[key]

            def _update(k=key, ek=ekey):
                st.session_state.brain_pad[k] = st.session_state[ek]
                mark_dirty()

            st.text_area("Content", key=ekey, on_change=_update, height=150)

            def _delete(k=key, ek=ekey):
                st.session_state.brain_pad.pop(k, None)
                st.session_state.pop(ek, None)
                mark_dirty()

            st.button("🗑️ Delete", key=f"del_{key}", on_click=_delete)

# ---- Ask StormBot
with tabs[1]:
    st.subheader("Ask StormBot")
    for i, pair in enumerate(st.session_state.history):
        with st.chat_message("user"):
            st.write(pair["user"])
        with st.chat_message("assistant"):
            st.write(pair["stormbot"])
            st.button(
                "Save reply to BrainPad",
                key=f"save_chat_{i}",
                on_click=add_to_pad,
                args=("AI-GENERATED IDEA", pair["stormbot"]),
            )

    with st.form("ask_form", clear_on_submit=True):
        question = st.text_area("Enter your question", height=100)
        asked = st.form_submit_button("Ask")
    if asked:
        if not question.strip():
            st.warning("Please enter a question first.")
        else:
            msgs = [{"role": "system", "content": chat_system_prompt()}]
            for pair in st.session_state.history[-10:]:
                msgs.append({"role": "user", "content": pair["user"]})
                msgs.append({"role": "assistant", "content": pair["stormbot"]})
            msgs.append({"role": "user", "content": question.strip()})
            with st.spinner("StormBot is thinking..."):
                reply = call_llm(msgs)
            if reply:
                st.session_state.history.append(
                    {"user": question.strip(), "stormbot": reply}
                )
                st.session_state.history = st.session_state.history[-10:]
                mark_dirty()
                st.rerun()

# ---- Wild ideas
with tabs[2]:
    st.subheader("⚡ Wild Idea Generator")
    num = st.number_input("Number of ideas", min_value=1, max_value=10, value=1, step=1)
    options = list(st.session_state.brain_pad.keys())
    # Drop selections whose notes were deleted or renamed
    if "wild_sel" in st.session_state:
        st.session_state["wild_sel"] = [
            x for x in st.session_state["wild_sel"] if x in options
        ]
    selected = st.multiselect(
        "Specific BrainPad notes to focus on", options, key="wild_sel"
    )
    extra = st.text_input("Additional context for StormBot (optional)")

    if st.button("Generate wild ideas"):
        pad = st.session_state.brain_pad
        empty_msg = "Empty. Continue building an idea on the basis of the user prompt."
        general = format_brain_pad(pad) or empty_msg
        specific = (
            "\n".join(f"{k}: {pad[k]}" for k in selected) if selected else empty_msg
        )
        prompt = (
            f"You are StormBot, the AI brainstorming assistant for {APP_NAME}. "
            "Your purpose is to help users generate, explore, and develop ideas "
            "creatively while remaining helpful and intellectually honest. "
            f"Generate {int(num)} unconventional, original, and intellectually "
            "interesting idea(s) inspired by the given context. "
            "Go beyond obvious extensions of existing ideas. "
            "Explore unexpected connections between different fields. "
            "Explain the idea, why it is interesting, and how it could potentially "
            "be developed. Avoid presenting speculation as established fact. "
            "Generate a wild and new idea related to the given context:\n\n"
            f"User prompt: {extra.strip() or 'None'}\n\n"
            f"BrainPad:\n{general}\n(This is general context. Skim through it for "
            "useful information, inspiration and connections.)\n\n"
            "Specific context from BrainPad (focus more on this and use it as the "
            f"main basis to form the ideas):\n{specific}"
        )
        with st.spinner("StormBot is thinking..."):
            st.session_state.wild_reply = call_llm(
                [{"role": "system", "content": prompt}]
            )

    if st.session_state.wild_reply:
        st.markdown("### ⚡ StormBot's wild idea ⚡")
        st.write(st.session_state.wild_reply)
        st.button(
            "Add these ideas to BrainPad",
            key="save_wild",
            on_click=add_to_pad,
            args=("StormIdea", st.session_state.wild_reply),
        )

# ---- Debate
with tabs[3]:
    st.subheader("🥊 Debate mode")
    st.caption("Debate StormBot to explore the advantages and disadvantages of your ideas.")
    debate = st.session_state.debate

    if debate is None:
        with st.form("debate_start"):
            topic = st.text_input("Debate topic")
            side = st.radio("Your side", ["for", "against"], horizontal=True)
            share = st.checkbox("Give StormBot access to my BrainPad")
            start = st.form_submit_button("Start debate")
        if start:
            if not topic.strip():
                st.warning("Please enter a debate topic.")
            else:
                ai_side = "against" if side == "for" else "for"
                system = f"""
You are StormBot, participating in a formal debate.

Topic: {topic.strip()}

User's position: {side}
Your position: {ai_side}
Defend your assigned position using logical reasoning.
Respond directly to the user's arguments.
Do not fabricate facts or statistics.
Remain respectful and acknowledge valid arguments.
Never switch your assigned position.

You are StormBot of {APP_NAME}, an assistant helping users generate and refine ideas.

This debate is intended to explore ideas, their advantages and disadvantages.

All ideas belong to the user and are refined through {APP_NAME}.
"""
                if share:
                    ctx = format_brain_pad(st.session_state.brain_pad) or "BrainPad is empty."
                else:
                    ctx = "No BrainPad access granted."
                messages = [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": f"Relevant BrainPad context:\n{ctx}\n\n"
                        "The debate is beginning.\nPresent your opening argument.",
                    },
                ]
                with st.spinner("StormBot is thinking..."):
                    opening = call_llm(messages)
                display = []
                if opening:
                    messages.append({"role": "assistant", "content": opening})
                    display.append(("assistant", opening))
                else:
                    st.info("StormBot couldn't give an opening argument. You can start the debate.")
                st.session_state.debate = {
                    "topic": topic.strip(),
                    "ai_side": ai_side,
                    "messages": messages,
                    "display": display,
                }
                st.rerun()
    else:
        st.markdown(
            f"**Topic:** {debate['topic']}  \n**StormBot argues:** {debate['ai_side']}"
        )
        for i, (role, text) in enumerate(debate["display"]):
            with st.chat_message(role):
                st.write(text)
                if role == "assistant":
                    label, prefix = "Save reply to BrainPad", "AI-GENERATED IDEA"
                else:
                    label, prefix = "Save my argument to BrainPad", "Note"
                st.button(
                    label,
                    key=f"save_debate_{i}",
                    on_click=add_to_pad,
                    args=(prefix, text),
                )

        with st.form("debate_arg", clear_on_submit=True):
            arg = st.text_area("Your argument", height=100)
            send = st.form_submit_button("Send")
        if send:
            if not arg.strip():
                st.warning("Please enter an argument.")
            else:
                msgs = debate["messages"] + [{"role": "user", "content": arg.strip()}]
                # setup messages + the last ten exchanges
                payload = msgs[:2] + msgs[2:][-20:]
                with st.spinner("StormBot is thinking..."):
                    reply = call_llm(payload)
                if reply:
                    debate["messages"] = msgs + [{"role": "assistant", "content": reply}]
                    debate["display"].append(("user", arg.strip()))
                    debate["display"].append(("assistant", reply))
                    st.rerun()

        if st.button("End debate"):
            st.session_state.debate = None
            st.rerun()

# ---- Permanent context
with tabs[4]:
    st.subheader("📌 Permanent context for StormBot chats")
    st.caption("Make sure it is free from any ambiguity. StormBot will use it in every chat.")
    with st.form("ctx_form", clear_on_submit=True):
        ctx_text = st.text_area("Context", height=100)
        add_ctx = st.form_submit_button("Add context")
    if add_ctx:
        if ctx_text.strip():
            st.session_state.permacontext[
                next_key(st.session_state.permacontext, "Extra context")
            ] = ctx_text.strip()
            mark_dirty()
            st.rerun()
        else:
            st.warning("No context entered.")
    for k in list(st.session_state.permacontext.keys()):
        c1, c2 = st.columns([8, 1])
        c1.markdown(f"**{k}:** {st.session_state.permacontext[k]}")
        if c2.button("🗑️", key=f"delctx_{k}"):
            del st.session_state.permacontext[k]
            mark_dirty()
            st.rerun()

# ---- Export
with tabs[5]:
    st.subheader("📄 Export")
    st.download_button(
        "Download BrainPad as Word file",
        data=build_docx_bytes(),
        file_name=f"{st.session_state.project_name or 'BrainPad'}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="export_docx",
    )
    st.download_button(
        "Download project (.brainpad.json)",
        data=build_json_text(),
        file_name=f"{st.session_state.project_name or 'project'}.brainpad.json",
        mime="application/json",
        on_click=mark_saved,
        key="export_json",
    )

# ---- About
with tabs[6]:
    st.subheader(f"About {APP_NAME}™")
    st.write(
        "BrainStormAI is built for project building and works well alongside "
        "general chatbots. It uses OpenRouter's NVIDIA Nemotron Super model and "
        "offers a full set of ideation tools:"
    )
    st.markdown(
        "- **Write your own notes** on a BrainPad\n"
        "- **Chat with StormBot** and save its replies\n"
        "- **Debate** StormBot to test ideas\n"
        "- **Generate wild ideas** for inspiration\n"
        "- **Save as JSON** and continue later\n"
        "- **Export to Word**\n\n"
        "Best suited for project brainstorming and recording your ideas and thoughts."
    )

# ---------------------------------------------------------------- sidebar
# Rendered last so it always reflects changes made earlier in this run
# (unsaved-changes warning and the JSON download are never one step behind).
with st.sidebar:
    st.markdown(f"## 🧠 {APP_NAME}™")
    st.caption(f"Mark {MARK_NUMBER} · Powered by NVIDIA Nemotron via OpenRouter")

    st.text_input("Project name", key="project_name", on_change=mark_dirty)
    if st.session_state.dirty:
        st.warning("Unsaved changes — download your project below.")

    st.download_button(
        "💾 Save project (.brainpad.json)",
        data=build_json_text(),
        file_name=f"{st.session_state.project_name or 'project'}.brainpad.json",
        mime="application/json",
        on_click=mark_saved,
        use_container_width=True,
        key="sidebar_json",
    )

    st.divider()
    st.markdown("**Continue an earlier project**")
    uploaded = st.file_uploader("Upload .brainpad.json", type=["json"], key="upload_json")
    st.button(
        "📂 Load project",
        use_container_width=True,
        on_click=do_load,
        disabled=uploaded is None,
    )
    st.button("🆕 New project", use_container_width=True, on_click=do_new)

    msg = st.session_state.pop("load_msg", None)
    if msg:
        (st.success if msg[0] == "success" else st.error)(msg[1])

    st.divider()
    try:
        has_secret = bool(st.secrets.get("OPENROUTER_API_KEY"))
    except Exception:
        has_secret = False
    if not has_secret:
        st.text_input(
            "OpenRouter API key",
            type="password",
            key="user_api_key",
            help="Used only in this session and never stored.",
        )
