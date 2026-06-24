from config import USER_PROFILE_PATH, PLAYBOOK_PATH


def load_memory():
    sections = []

    for label, path in [
        ("USER PROFILE", USER_PROFILE_PATH),
        ("PLAYBOOK", PLAYBOOK_PATH)
    ]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                sections.append(f"--- {label} ---\n{content}")
        except FileNotFoundError:
            sections.append(f"--- {label} ---\n[NOT FOUND]")

    return "\n\n".join(sections)