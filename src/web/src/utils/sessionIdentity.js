export const UNKNOWN_USER_NAME = 'unknown';

export const createSessionId = () =>
    `session_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;

export const normalizeSessionUsername = (username) => {
    const cleanUsername = typeof username === 'string' ? username.trim() : '';
    if (!cleanUsername || cleanUsername.toLowerCase() === UNKNOWN_USER_NAME) {
        return UNKNOWN_USER_NAME;
    }
    return cleanUsername;
};

export const buildSessionIdentity = ({
    sessionId = createSessionId(),
    username,
    userName,
    needsIdentification,
    isNewUser,
    userStatus,
} = {}) => {
    const normalizedUserName = normalizeSessionUsername(userName ?? username);
    const isKnownUser = normalizedUserName !== UNKNOWN_USER_NAME;

    return {
        sessionId,
        userName: normalizedUserName,
        isNewUser: typeof isNewUser === 'boolean' ? isNewUser : !isKnownUser,
        needsIdentification: typeof needsIdentification === 'boolean' ? needsIdentification : !isKnownUser,
        userStatus: userStatus || (isKnownUser ? 'existing' : 'new_unknown'),
    };
};
