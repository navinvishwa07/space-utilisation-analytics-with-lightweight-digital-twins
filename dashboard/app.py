"""Streamlit dashboard for SIET (Space Infrastructure Exchange Twin)."""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

import pandas as pd
import requests
import streamlit as st

# ==========================================
# Configuration & Constants
# ==========================================
# Point this to your local FastAPI server
API_BASE_URL = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="SIET Dashboard",
    page_icon="🏢",
    layout="wide",
)

# ==========================================
# API Helper Functions (Defensive Programming)
# ==========================================
def fetch_prediction(room_id: int, target_date: str, time_slot: str) -> Optional[Dict[str, Any]]:
    """Calls the backend Prediction module."""
    try:
        response = requests.post(
            f"{API_BASE_URL}/predict_availability",
            json={
                "room_id": room_id,
                "date": target_date,
                "time_slot": time_slot,
            },
            timeout=5,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Backend connection failed: {e}")
        return None


def fetch_optimization(
    target_date: str, 
    time_slot: str, 
    idle_threshold: float, 
    stakeholder_cap: float
) -> Optional[Dict[str, Any]]:
    """Calls the backend Matchmaker/Optimization module."""
    try:
        response = requests.post(
            f"{API_BASE_URL}/optimize_allocation",
            json={
                "requested_date": target_date,
                "requested_time_slot": time_slot,
                "idle_probability_threshold": idle_threshold,
                "stakeholder_usage_cap": stakeholder_cap,
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Optimization failed: {e}")
        return None


def fetch_simulation(capacity_override: Dict[int, int]) -> Optional[Dict[str, Any]]:
    """Calls the backend What-If Simulation Sandbox."""
    try:
        response = requests.post(
            f"{API_BASE_URL}/simulate",
            json={
                "temporary_constraints": {
                    "capacity_override": capacity_override
                }
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Simulation failed: {e}")
        return None


# ==========================================
# UI Page Functions
# ==========================================
def render_prediction_page() -> None:
    st.header("🔮 AI Idle Prediction")
    st.markdown("Predict the probability that a specific room will be idle.")

    col1, col2, col3 = st.columns(3)
    with col1:
        room_id = st.number_input("Room ID (1-10)", min_value=1, max_value=10, value=1)
    with col2:
        target_date = st.date_input("Target Date", datetime.date(2026, 2, 23))
    with col3:
        time_slot = st.selectbox("Time Slot", ["09-11", "11-13", "14-16", "16-18"])

    if st.button("Predict Availability", type="primary"):
        with st.spinner("Asking the Fortune Teller..."):
            result = fetch_prediction(room_id, str(target_date), time_slot)
            
            if result:
                idle_prob = result.get("idle_probability", 0.0)
                confidence = result.get("confidence_score", 0.0)
                
                st.subheader("Prediction Results")
                metric_col1, metric_col2 = st.columns(2)
                metric_col1.metric("Idle Probability", f"{idle_prob * 100:.1f}%")
                metric_col2.metric("AI Confidence", f"{confidence * 100:.1f}%")
                
                if idle_prob > 0.7:
                    st.success("High probability this room will be empty!")
                elif idle_prob > 0.4:
                    st.warning("Uncertain. Room might be in use.")
                else:
                    st.error("High probability this room is booked.")


def render_optimization_page() -> None:
    st.header("⚖️ Allocation Matchmaker")
    st.markdown("Run the OR-Tools optimizer to fairly assign pending requests to available rooms.")

    col1, col2 = st.columns(2)
    with col1:
        target_date = st.date_input("Allocation Date", datetime.date(2026, 2, 23))
        time_slot = st.selectbox("Allocation Time Slot", ["09-11", "11-13", "14-16", "16-18"])
    with col2:
        idle_threshold = st.slider("Minimum Idle Probability Threshold", 0.0, 1.0, 0.5)
        stakeholder_cap = st.slider("Stakeholder Usage Cap", 0.1, 1.0, 0.7)

    if st.button("Run Optimizer", type="primary"):
        with st.spinner("Crunching constraints and building matches..."):
            result = fetch_optimization(str(target_date), time_slot, idle_threshold, stakeholder_cap)
            
            if result:
                st.subheader("Optimization Scorecard")
                metric_col1, metric_col2 = st.columns(2)
                metric_col1.metric("Objective Value (Score)", round(result.get("objective_value", 0), 2))
                metric_col2.metric("Fairness Metric", f"{result.get('fairness_metric', 0) * 100:.1f}%")

                allocations = result.get("allocations", [])
                if allocations:
                    st.write("### Successful Matches")
                    df = pd.DataFrame(allocations)
                    st.dataframe(df, use_container_width=True)
                else:
                    st.info("No successful matches could be made with the current constraints.")


def render_simulation_page() -> None:
    st.header("🧪 What-If Sandbox")
    st.markdown("Simulate capacity overrides without modifying the live database.")

    st.write("### Temporary Constraints")
    col1, col2 = st.columns(2)
    with col1:
        override_room_id = st.number_input("Override Room ID", min_value=1, max_value=10, value=3)
    with col2:
        new_capacity = st.number_input("Temporary Capacity", min_value=0, max_value=200, value=0)

    if st.button("Run Simulation", type="primary"):
        with st.spinner("Running alternate timeline..."):
            result = fetch_simulation({override_room_id: new_capacity})
            
            if result:
                st.subheader("Simulation Impact")
                
                baseline = result.get("baseline", {})
                simulation = result.get("simulation", {})
                delta = result.get("delta", {})

                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Baseline Utilization", f"{baseline.get('utilization', 0)*100:.1f}%")
                col_b.metric("Simulated Utilization", f"{simulation.get('utilization', 0)*100:.1f}%", delta=f"{delta.get('utilization_change', 0)*100:.1f}%")
                col_c.metric("Lost Requests", simulation.get("unassigned_count", 0), delta=delta.get("unassigned_change", 0), delta_color="inverse")


# ==========================================
# Main App Router
# ==========================================
def main() -> None:
    st.sidebar.title("SIET Digital Twin")
    st.sidebar.markdown("---")
    
    page = st.sidebar.radio(
        "Navigation Module",
        ["AI Prediction", "Allocation Engine", "What-If Simulation"]
    )

    st.sidebar.markdown("---")
    st.sidebar.caption("System Engine: Active")
    st.sidebar.caption("ML Backend: scikit-learn")
    st.sidebar.caption("Optimizer: OR-Tools")

    if page == "AI Prediction":
        render_prediction_page()
    elif page == "Allocation Engine":
        render_optimization_page()
    elif page == "What-If Simulation":
        render_simulation_page()

if __name__ == "__main__":
    main()