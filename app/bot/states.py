from aiogram.fsm.state import State, StatesGroup


class EnrollStates(StatesGroup):
    waiting_for_photos = State()


class PromptCreateStates(StatesGroup):
    waiting_scope = State()
    waiting_name = State()
    waiting_content = State()


class BranchCreateStates(StatesGroup):
    waiting_name = State()
    waiting_model = State()
    waiting_system_prompt = State()


class FollowupChainStates(StatesGroup):
    waiting_branch = State()
    waiting_name = State()
    waiting_event = State()


class FollowupStepStates(StatesGroup):
    waiting_chain_id = State()
    waiting_order = State()
    waiting_delay = State()
    waiting_send_mode = State()
    waiting_content = State()
