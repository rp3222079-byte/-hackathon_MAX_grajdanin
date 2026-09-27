_user_states = {}
#получить текущее состояние пользователя
def get_state(user_id):
    return _user_states.get(user_id)
#установить пользователю новый этап и дополнительные данные 
def  set_state(user_id, step, data=None):
    if data is None: 
        data = {}
    _user_states[user_id] = {"step" : step, "data": data}
#обновить текущие данные о состоянии пользоваьеля
def update_data(user_id, **kwargs):
    state = _user_states.get(user_id)
    if state is not None: 
        state["data"].update(kwargs)
#удалить состояние пользователя
def clear_state(user_id):
    _user_states.pop(user_id, None)

