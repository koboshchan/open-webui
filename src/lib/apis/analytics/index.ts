import { WEBUI_API_BASE_URL } from '$lib/constants';

const readError = async (res: Response) => {
	const text = await res.text().catch(() => '');
	try {
		return JSON.parse(text);
	} catch {
		return { detail: text?.trim() ? `${res.status} ${res.statusText}: ${text.trim().slice(0, 200)}` : `${res.status} ${res.statusText}`, status: res.status };
	}
};

export type APICallUserOrderBy = 'count' | 'name' | 'input_tokens' | 'output_tokens';
export type SortDirection = 'asc' | 'desc';

export const getAPICallCollection = async (token: string = '') => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/analytics/api-calls/collection`, {
		headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw await readError(res);
	return res.json();
};

export const setAPICallCollection = async (token: string = '', enabled: boolean) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/analytics/api-calls/collection`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ enabled })
	});
	if (!res.ok) throw await readError(res);
	return res.json();
};

export type APICallDashboard = {
	summary: {
		total_calls: number;
		input_tokens: number;
		output_tokens: number;
		total_tokens: number;
		total_users: number;
	};
	timeline: { date: string; models: Record<string, number>; token_models: Record<string, number> }[];
	models: {
		model_id: string | null;
		count: number;
		input_tokens: number;
		output_tokens: number;
		total_tokens: number;
	}[];
	users: {
		user_id: string | null;
		name: string | null;
		email: string | null;
		count: number;
		input_tokens: number;
		output_tokens: number;
		total_tokens: number;
	}[];
};

export const getAPICallDashboard = async (
	token: string = '',
	startDate: number | null = null,
	endDate: number | null = null,
	groupId: string | null = null,
	granularity: 'hourly' | 'daily' = 'daily',
	timezone: string = 'UTC',
	userOrderBy: APICallUserOrderBy = 'count',
	userDirection: SortDirection = 'desc'
): Promise<APICallDashboard> => {
	const searchParams = new URLSearchParams();
	if (startDate != null) searchParams.append('start_date', startDate.toString());
	if (endDate != null) searchParams.append('end_date', endDate.toString());
	if (groupId) searchParams.append('group_id', groupId);
	searchParams.append('granularity', granularity);
	searchParams.append('timezone', timezone);
	searchParams.append('user_order_by', userOrderBy);
	searchParams.append('user_direction', userDirection);
	const res = await fetch(`${WEBUI_API_BASE_URL}/analytics/api-calls/dashboard?${searchParams}`, {
		headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw await readError(res);
	return res.json();
};

export const getModelAnalytics = async (
	token: string = '',
	startDate: number | null = null,
	endDate: number | null = null,
	groupId: string | null = null
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (startDate) searchParams.append('start_date', startDate.toString());
	if (endDate) searchParams.append('end_date', endDate.toString());
	if (groupId) searchParams.append('group_id', groupId);

	const res = await fetch(`${WEBUI_API_BASE_URL}/analytics/models?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getUserAnalytics = async (
	token: string = '',
	startDate: number | null = null,
	endDate: number | null = null,
	limit: number = 50,
	groupId: string | null = null
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (startDate) searchParams.append('start_date', startDate.toString());
	if (endDate) searchParams.append('end_date', endDate.toString());
	if (limit) searchParams.append('limit', limit.toString());
	if (groupId) searchParams.append('group_id', groupId);

	const res = await fetch(`${WEBUI_API_BASE_URL}/analytics/users?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getMessages = async (
	token: string = '',
	modelId: string | null = null,
	userId: string | null = null,
	chatId: string | null = null,
	startDate: number | null = null,
	endDate: number | null = null,
	skip: number = 0,
	limit: number = 50
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (modelId) searchParams.append('model_id', modelId);
	if (userId) searchParams.append('user_id', userId);
	if (chatId) searchParams.append('chat_id', chatId);
	if (startDate) searchParams.append('start_date', startDate.toString());
	if (endDate) searchParams.append('end_date', endDate.toString());
	if (skip) searchParams.append('skip', skip.toString());
	if (limit) searchParams.append('limit', limit.toString());

	const res = await fetch(`${WEBUI_API_BASE_URL}/analytics/messages?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getSummary = async (
	token: string = '',
	startDate: number | null = null,
	endDate: number | null = null,
	groupId: string | null = null
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (startDate) searchParams.append('start_date', startDate.toString());
	if (endDate) searchParams.append('end_date', endDate.toString());
	if (groupId) searchParams.append('group_id', groupId);

	const res = await fetch(`${WEBUI_API_BASE_URL}/analytics/summary?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getDailyStats = async (
	token: string = '',
	startDate: number | null = null,
	endDate: number | null = null,
	granularity: 'hourly' | 'daily' = 'daily',
	groupId: string | null = null
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (startDate) searchParams.append('start_date', startDate.toString());
	if (endDate) searchParams.append('end_date', endDate.toString());
	searchParams.append('granularity', granularity);
	if (groupId) searchParams.append('group_id', groupId);

	const res = await fetch(`${WEBUI_API_BASE_URL}/analytics/daily?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getTokenUsage = async (
	token: string = '',
	startDate: number | null = null,
	endDate: number | null = null,
	groupId: string | null = null
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (startDate) searchParams.append('start_date', startDate.toString());
	if (endDate) searchParams.append('end_date', endDate.toString());
	if (groupId) searchParams.append('group_id', groupId);

	const res = await fetch(`${WEBUI_API_BASE_URL}/analytics/tokens?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getModelChats = async (
	token: string = '',
	modelId: string,
	startDate: number | null = null,
	endDate: number | null = null,
	skip: number = 0,
	limit: number = 50,
	orderBy: string | null = null,
	direction: string | null = null
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (startDate) searchParams.append('start_date', startDate.toString());
	if (endDate) searchParams.append('end_date', endDate.toString());
	if (skip) searchParams.append('skip', skip.toString());
	if (limit) searchParams.append('limit', limit.toString());
	if (orderBy) searchParams.append('order_by', orderBy);
	if (direction) searchParams.append('direction', direction);

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/analytics/models/${encodeURIComponent(modelId)}/chats?${searchParams.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getModelOverview = async (token: string = '', modelId: string, days: number = 30) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('days', days.toString());

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/analytics/models/${encodeURIComponent(modelId)}/overview?${searchParams.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
