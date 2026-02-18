from pydantic import BaseModel


class TemplateView(BaseModel):
    code: str
    title: str
    description: str
    width: int
    height: int
    num_outputs: int
    cost_credits: int


class NanoEnrollResponse(BaseModel):
    identity_id: str
