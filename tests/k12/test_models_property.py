# Feature: k12-math-guided-tutoring, Property 12: 解题状态序列化往返一致性
"""
Property-based test for SolvingSessionState serialization round-trip consistency.

**Validates: Requirements 8.2**

For any valid SolvingSessionState object, serializing it to JSON and
deserializing back should produce an object equal to the original.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from deeptutor.k12.models import SolvingSessionState


# --- Custom strategies ---

# Strategy for simple JSON-safe values (basic types only)
json_safe_values = st.one_of(
    st.text(max_size=50),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    st.booleans(),
)

# Strategy for simple dicts with string keys and basic-type values
simple_dict = st.dictionaries(
    keys=st.text(min_size=1, max_size=20),
    values=json_safe_values,
    max_size=5,
)

# Strategy for guidance level
guidance_level_st = st.sampled_from(["full", "moderate", "minimal"])


# Strategy for generating valid SolvingSessionState instances
@st.composite
def solving_session_state_strategy(draw):
    current_step = draw(st.integers(min_value=0, max_value=100))
    total_steps = draw(st.integers(min_value=current_step, max_value=200))

    return SolvingSessionState(
        problem_text=draw(st.text(max_size=200)),
        analysis_result=draw(simple_dict),
        current_step=current_step,
        total_steps=total_steps,
        completed_steps=draw(st.lists(st.integers(min_value=0, max_value=200), max_size=10)),
        error_count=draw(
            st.dictionaries(
                keys=st.text(min_size=1, max_size=20),
                values=st.integers(min_value=0, max_value=100),
                max_size=5,
            )
        ),
        guidance_level=draw(guidance_level_st),
        steps=draw(st.lists(simple_dict, max_size=10)),
        independent_steps=draw(st.lists(st.integers(min_value=0, max_value=200), max_size=10)),
        is_complete=draw(st.booleans()),
        is_abandoned=draw(st.booleans()),
    )


# --- Property test ---


@given(state=solving_session_state_strategy())
@settings(max_examples=100)
def test_solving_session_state_serialization_roundtrip(state: SolvingSessionState):
    """
    Property 12: For any valid SolvingSessionState, serializing to JSON
    and deserializing back produces an equal object.

    **Validates: Requirements 8.2**
    """
    # Serialize to JSON
    json_str = state.model_dump_json()

    # Deserialize back
    restored = SolvingSessionState.model_validate_json(json_str)

    # Assert equality
    assert restored == state
