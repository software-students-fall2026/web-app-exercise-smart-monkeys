// Join a study session using the Flask backend API.
async function joinSession(sessionId) {
    try {
        // Get the CSRF token required for POST requests.
        const csrfResponse = await fetch("/api/auth/csrf");
        if (!csrfResponse.ok) {
            throw new Error("Could not get the security token.");
        }

        const { csrf_token } = await csrfResponse.json();

        // Send the request to join the selected session.
        const response = await fetch(
            `/api/sessions/${encodeURIComponent(sessionId)}/join`,
            {
                method: "POST",
                headers: {
                    "X-CSRFToken": csrf_token
                },
                credentials: "same-origin"
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Could not join the session.");
        }

        // Return the updated session so the UI can refresh its details.
        return data.session;

    } catch (error) {
        console.error("Join session failed:", error);
        throw error;
    }
}

// Leave a study session using the Flask backend API.
async function leaveSession(sessionId) {
    try {
        // Get the CSRF token required for POST requests.
        const csrfResponse = await fetch("/api/auth/csrf");

        if (!csrfResponse.ok) {
            throw new Error("Could not get the security token.");
        }

        const { csrf_token } = await csrfResponse.json();

        // Send the request to leave the selected session.
        const response = await fetch(
            `/api/sessions/${encodeURIComponent(sessionId)}/leave`,
            {
                method: "POST",
                headers: {
                    "X-CSRFToken": csrf_token
                },
                credentials: "same-origin"
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Could not leave the session.");
        }

        // Return the updated session information.
        return data.session;

    } catch (error) {
        console.error("Leave session failed:", error);
        throw error;
    }
}
// Connect Join and Leave buttons to their API functions.
document.addEventListener("click", async (event) => {
    const button = event.target.closest(
        "[data-action='join-session'], [data-action='leave-session']"
    );

    if (!button || button.disabled) return;

    const sessionId = button.dataset.sessionId;
    const action = button.dataset.action;

    if (!sessionId) {
        console.error("Missing session ID.");
        return;
    }

    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = "Processing...";

    try {
        const session = action === "join-session"
            ? await joinSession(sessionId)
            : await leaveSession(sessionId);

        // Update the participant count if displayed.
        const count = document.querySelector(
            `[data-participant-count="${CSS.escape(sessionId)}"]`
        );

        if (count) {
            count.textContent =
                `${session.participant_count}/${session.max_participants}`;
        }

        
        // Refresh the button using the latest session data.
        await updateSessionButton(button);


    } catch (error) {
            alert(error.message);
            button.textContent = originalText;
            button.disabled = false;
        }
    });

// Check whether the logged-in student has joined a session.
async function getSessionParticipation(sessionId) {
    // Get the currently logged-in student.
    const userResponse = await fetch("/api/auth/me");

    if (!userResponse.ok) {
        throw new Error("Please log in to view your participation.");
    }

    const { user } = await userResponse.json();

    // Get the session details, including participant IDs.
    const sessionResponse = await fetch(
        `/api/sessions/${encodeURIComponent(sessionId)}`
    );

    if (!sessionResponse.ok) {
        throw new Error("Could not load session details.");
    }

    const { session } = await sessionResponse.json();

    // Compare IDs to determine whether the student has joined.
    const hasJoined = session.participant_ids.some(
        (id) => String(id) === String(user._id)
    );
    return {
        hasJoined,
        session,
        user
    };
}

// Update a session button based on the student's participation.
async function updateSessionButton(button) {
    const sessionId = button.dataset.sessionId;

    if (!sessionId) return;

    button.disabled = true;
    button.textContent = "Loading...";

    try {
        const { hasJoined, session, user } =
            await getSessionParticipation(sessionId);

        const isOrganizer = session.organizer_id === user._id;

        if (isOrganizer) {
            button.textContent = "Your Session";
            button.disabled = true;
            return;
        }

        if (hasJoined) {
            button.dataset.action = "leave-session";
            button.textContent = "Leave Session";
            button.disabled = false;

        } else if (
            session.registration_open &&
            session.display_status !== "full" &&
            new Date(session.start_at).getTime() > Date.now() &&
            session.participant_count < session.max_participants
        ) {
            button.dataset.action = "join-session";
            button.textContent = "Join Session";
            button.disabled = false;
        } else {
            button.textContent = "Registration Closed";
            button.disabled = true;
        }
    } catch (error) {
        console.error("Could not update session button:", error);
        button.textContent = "Unavailable";
        button.disabled = true;
    }
}

// Initialize session buttons when the page loads.
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-session-id][data-action]").forEach(
        (button) => updateSessionButton(button)
    );
});