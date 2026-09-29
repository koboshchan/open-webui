<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { models } from '$lib/stores';
	import {
		getSummary,
		getModelAnalytics,
		getUserAnalytics,
		getDailyStats,
		getTokenUsage,
		getAPICallCollection,
		setAPICallCollection,
		getAPICallDashboard,
		type APICallDashboard
	} from '$lib/apis/analytics';
	import { getGroups } from '$lib/apis/groups';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChartLine from './ChartLine.svelte';
	import AnalyticsModelModal from './AnalyticsModelModal.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { formatNumber } from '$lib/utils';
	import { goto } from '$app/navigation';

	const i18n = getContext('i18n');

	// Time period - persist in localStorage
	let selectedPeriod =
		(typeof localStorage !== 'undefined' && localStorage.getItem('analyticsPeriod')) || '7d';

	// Custom date range (YYYY-MM-DD) - persist in localStorage
	let customStart =
		(typeof localStorage !== 'undefined' && localStorage.getItem('analyticsCustomStart')) || '';
	let customEnd =
		(typeof localStorage !== 'undefined' && localStorage.getItem('analyticsCustomEnd')) || '';

	$: periods = [
		{ value: '24h', label: $i18n.t('Last 24 hours') },
		{ value: '7d', label: $i18n.t('Last 7 days') },
		{ value: '30d', label: $i18n.t('Last 30 days') },
		{ value: '90d', label: $i18n.t('Last 90 days') },
		{ value: 'all', label: $i18n.t('All time') },
		{ value: 'custom', label: $i18n.t('Custom range') }
	];
	const chartPeriods: Record<string, 'hour' | 'week' | 'month' | 'year' | 'all'> = {
		'24h': 'hour',
		'7d': 'week',
		'30d': 'month',
		'90d': 'year',
		all: 'all'
	};

	// User group filter
	let groups: Array<{ id: string; name: string }> = [];
	let selectedGroupId: string | null = null;

	const getDateRange = (period: string): { start: number | null; end: number | null } => {
		const now = Math.floor(Date.now() / 1000);
		const day = 86400;
		switch (period) {
			case '24h':
				return { start: now - day, end: now };
			case '7d':
				return { start: now - 7 * day, end: now };
			case '30d':
				return { start: now - 30 * day, end: now };
			case '90d':
				return { start: now - 90 * day, end: now };
			case 'custom': {
				// Date inputs are local calendar days, including days with a DST change.
				const start = customStart ? Math.floor(new Date(`${customStart}T00:00:00`).getTime() / 1000) : null;
				const endDay = customEnd ? new Date(`${customEnd}T00:00:00`) : null;
				if (endDay) endDay.setDate(endDay.getDate() + 1);
				const end = endDay ? Math.floor(endDay.getTime() / 1000) - 1 : null;
				return { start, end };
			}
			default:
				return { start: null, end: null };
		}
	};

	// Data
	let summary = { total_messages: 0, total_chats: 0, total_models: 0, total_users: 0 };
	let modelStats: Array<{
		model_id: string;
		count: number;
		unique_users?: number;
		unique_chats?: number;
		name?: string;
	}> = [];
	let userStats: Array<{ user_id: string; name?: string; email?: string; count: number }> = [];
	let dailyStats: Array<{ date: string; models: Record<string, number> }> = [];
	let tokenStats: Record<
		string,
		{ input_tokens: number; output_tokens: number; total_tokens: number }
	> = {};
	let totalTokens = { input: 0, output: 0, total: 0 };
	let apiCallCollectionEnabled = false;
	let collectionLoaded = false;
	let collectionError = false;
	let apiDashboard: APICallDashboard = {
		summary: { total_calls: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, total_users: 0 },
		timeline: [],
		routes: [],
		users: []
	};
	let apiCallCollectionSaving = false;
	let loadVersion = 0;
	let dashboardError = false;

	let loading = true;

	// Selected model for drill-down
	let selectedModel: { id: string; name: string } | null = null;
	let showModelModal = false;

	// Sorting
	let modelOrderBy = 'count';
	let modelDirection: 'asc' | 'desc' = 'desc';
	let userOrderBy = 'count';
	let userDirection: 'asc' | 'desc' = 'desc';
	let apiUserOrderBy: 'name' | 'count' | 'input_tokens' | 'output_tokens' = 'count';
	let apiUserDirection: 'asc' | 'desc' = 'desc';
	let routeOrderBy: 'path' | 'count' | 'input_tokens' | 'output_tokens' = 'count';
	let routeDirection: 'asc' | 'desc' = 'desc';

	const toggleApiUserSort = (key: typeof apiUserOrderBy) => {
		if (apiUserOrderBy === key) apiUserDirection = apiUserDirection === 'asc' ? 'desc' : 'asc';
		else {
			apiUserOrderBy = key;
			apiUserDirection = key === 'name' ? 'asc' : 'desc';
		}
	};

	const toggleRouteSort = (key: typeof routeOrderBy) => {
		if (routeOrderBy === key) routeDirection = routeDirection === 'asc' ? 'desc' : 'asc';
		else {
			routeOrderBy = key;
			routeDirection = key === 'path' ? 'asc' : 'desc';
		}
	};

	const toggleModelSort = (key: string) => {
		if (modelOrderBy === key) {
			modelDirection = modelDirection === 'asc' ? 'desc' : 'asc';
		} else {
			modelOrderBy = key;
			modelDirection = key === 'name' ? 'asc' : 'desc';
		}
	};

	const toggleUserSort = (key: string) => {
		if (userOrderBy === key) {
			userDirection = userDirection === 'asc' ? 'desc' : 'asc';
		} else {
			userOrderBy = key;
			userDirection = key === 'user_id' ? 'asc' : 'desc';
		}
	};

	const loadDashboard = async () => {
		const version = ++loadVersion;
		loading = true;
		dashboardError = false;
		try {
			const { start, end } = getDateRange(selectedPeriod);
			const granularity = selectedPeriod === '24h' ? 'hourly' : 'daily';
			if (apiCallCollectionEnabled) {
				const result = await getAPICallDashboard(
					localStorage.token,
					start,
					end,
					selectedGroupId,
					granularity,
					Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
				);
				if (version === loadVersion) apiDashboard = result;
				return;
			}
			const [summaryRes, modelsRes, usersRes, dailyRes, tokensRes] = await Promise.all([
				getSummary(localStorage.token, start, end, selectedGroupId),
				getModelAnalytics(localStorage.token, start, end, selectedGroupId),
				getUserAnalytics(localStorage.token, start, end, 50, selectedGroupId),
				getDailyStats(localStorage.token, start, end, granularity, selectedGroupId),
				getTokenUsage(localStorage.token, start, end, selectedGroupId)
			]);
			if (version !== loadVersion) return;

			summary = summaryRes ?? summary;

			const modelsMap = new Map($models.map((m) => [m.id, m.name || m.id]));
			modelStats = (modelsRes?.models ?? []).map((entry) => ({
				...entry,
				name: modelsMap.get(entry.model_id) || entry.model_id
			}));

			userStats = usersRes?.users ?? [];
			dailyStats = dailyRes?.data ?? [];

			// Process token data
			if (tokensRes) {
				tokenStats = {};
				for (const m of tokensRes.models) {
					tokenStats[m.model_id] = {
						input_tokens: m.input_tokens,
						output_tokens: m.output_tokens,
						total_tokens: m.total_tokens
					};
				}
				totalTokens = {
					input: tokensRes.total_input_tokens,
					output: tokensRes.total_output_tokens,
					total: tokensRes.total_tokens
				};
			}
		} catch (err) {
			console.error('Dashboard load failed:', err);
			if (version === loadVersion) dashboardError = true;
		} finally {
			if (version === loadVersion) loading = false;
		}
	};

	const toggleAPICallCollection = async () => {
		apiCallCollectionSaving = true;
		try {
			const result = await setAPICallCollection(localStorage.token, !apiCallCollectionEnabled);
			apiCallCollectionEnabled = result.enabled;
		} catch (err) {
			console.error('Could not update API call collection:', err);
		}
		apiCallCollectionSaving = false;
	};

	// Reload when the period, group, or custom range changes.
	// In custom mode, wait until both dates are set to avoid a half-specified query.
	$: if (collectionLoaded && selectedPeriod === 'custom' && !(customStart && customEnd)) {
		loading = false;
	} else if (collectionLoaded && !collectionError && selectedPeriod) {
		// reference customStart/customEnd so this block reruns when they change
		customStart;
		customEnd;
		selectedGroupId;
		apiCallCollectionEnabled;
		loadDashboard();
	}

	onMount(async () => {
		const [groupsResult, collectionResult] = await Promise.allSettled([
			getGroups(localStorage.token),
			getAPICallCollection(localStorage.token)
		]);
		if (groupsResult.status === 'fulfilled') groups = groupsResult.value ?? [];
		else console.error('Failed to load groups:', groupsResult.reason);
		if (collectionResult.status === 'fulfilled') {
			apiCallCollectionEnabled = Boolean(collectionResult.value?.enabled);
		} else {
			collectionError = true;
			console.error('Failed to load API call collection setting:', collectionResult.reason);
		}
		collectionLoaded = true;
	});

	$: sortedRoutes = [...apiDashboard.routes].sort((a, b) => {
		const compare = routeOrderBy === 'path'
			? `${a.method} ${a.path}`.localeCompare(`${b.method} ${b.path}`)
			: a[routeOrderBy] - b[routeOrderBy];
		return routeDirection === 'asc' ? compare : -compare;
	});

	$: sortedApiUsers = [...apiDashboard.users].sort((a, b) => {
		let compare: number;
		if (apiUserOrderBy === 'name') {
			compare = (a.name || a.email || a.user_id || '').localeCompare(
				b.name || b.email || b.user_id || ''
			);
		} else if (apiUserOrderBy === 'input_tokens') {
			compare = a.input_tokens - b.input_tokens;
		} else if (apiUserOrderBy === 'output_tokens') {
			compare = a.output_tokens - b.output_tokens;
		} else {
			compare = a.count - b.count;
		}
		return apiUserDirection === 'asc' ? compare : -compare;
	});

	$: sortedModels = [...modelStats].sort((a, b) => {
		if (modelOrderBy === 'name') {
			return modelDirection === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
		}
		if (modelOrderBy === 'tokens') {
			const aTokens = tokenStats[a.model_id]?.total_tokens ?? 0;
			const bTokens = tokenStats[b.model_id]?.total_tokens ?? 0;
			return modelDirection === 'asc' ? aTokens - bTokens : bTokens - aTokens;
		}
		if (modelOrderBy === 'users') {
			const aUsers = a.unique_users ?? 0;
			const bUsers = b.unique_users ?? 0;
			return modelDirection === 'asc' ? aUsers - bUsers : bUsers - aUsers;
		}
		if (modelOrderBy === 'chats') {
			const aChats = a.unique_chats ?? 0;
			const bChats = b.unique_chats ?? 0;
			return modelDirection === 'asc' ? aChats - bChats : bChats - aChats;
		}
		return modelDirection === 'asc' ? a.count - b.count : b.count - a.count;
	});

	$: sortedUsers = [...userStats].sort((a, b) => {
		if (userOrderBy === 'name') {
			const nameA = a.name || a.user_id;
			const nameB = b.name || b.user_id;
			return userDirection === 'asc' ? nameA.localeCompare(nameB) : nameB.localeCompare(nameA);
		}
		if (userOrderBy === 'tokens') {
			const aTokens = a.total_tokens ?? 0;
			const bTokens = b.total_tokens ?? 0;
			return userDirection === 'asc' ? aTokens - bTokens : bTokens - aTokens;
		}
		return userDirection === 'asc' ? a.count - b.count : b.count - a.count;
	});

	$: totalModelMessages = modelStats.reduce((sum, m) => sum + m.count, 0);

	// Persist period selection
	$: if (typeof localStorage !== 'undefined' && selectedPeriod) {
		localStorage.setItem('analyticsPeriod', selectedPeriod);
	}

	// Persist custom date range
	$: if (typeof localStorage !== 'undefined') {
		localStorage.setItem('analyticsCustomStart', customStart);
		localStorage.setItem('analyticsCustomEnd', customEnd);
	}
</script>

<div class="flex items-center justify-between mb-2 gap-2">
	<h2 class="text-sm font-medium text-gray-900 dark:text-white shrink-0">
		{$i18n.t('Analytics')}
	</h2>
	<div class="flex items-center gap-2 flex-wrap justify-end min-w-0">
		{#if groups.length > 0}
			<select
				bind:value={selectedGroupId}
				class="w-fit pr-8 rounded-sm px-2 text-xs bg-transparent outline-none text-right"
			>
				<option value={null}>{$i18n.t('All Users')}</option>
				{#each groups as group}
					<option value={group.id}>{group.name}</option>
				{/each}
			</select>
		{/if}
		{#if selectedPeriod === 'custom'}
			<input
				type="date"
				bind:value={customStart}
				max={customEnd || undefined}
				class="w-fit rounded-sm px-2 text-xs bg-transparent outline-none dark:scheme-dark"
			/>
			<span class="text-xs text-gray-400">–</span>
			<input
				type="date"
				bind:value={customEnd}
				min={customStart || undefined}
				class="w-fit rounded-sm px-2 text-xs bg-transparent outline-none dark:scheme-dark"
			/>
		{/if}
		<select
			bind:value={selectedPeriod}
			class="w-fit pr-8 rounded-sm px-2 text-xs bg-transparent outline-none text-right"
		>
			{#each periods as period}
				<option value={period.value}>{period.label}</option>
			{/each}
		</select>
		<button
			type="button"
			on:click={toggleAPICallCollection}
			disabled={apiCallCollectionSaving || !collectionLoaded || collectionError}
			aria-pressed={apiCallCollectionEnabled}
			class="rounded px-2 py-1 text-xs border border-gray-200 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
		>
			{$i18n.t('API call collection')}: {apiCallCollectionEnabled ? $i18n.t('On') : $i18n.t('Off')}
		</button>
	</div>
</div>

{#if collectionError}
	<div class="text-sm text-red-500 py-8 text-center">{$i18n.t('Failed to load analytics settings')}</div>
{:else if !collectionLoaded || loading}
	<div class="my-10 flex justify-center"><Spinner className="size-5" /></div>
{:else if dashboardError}
	<div class="text-sm text-red-500 py-8 text-center">{$i18n.t('Failed to load analytics data')}</div>
{:else if selectedPeriod === 'custom' && !(customStart && customEnd)}
	<div class="text-sm text-gray-400 py-8 text-center">{$i18n.t('Select a start and end date')}</div>
{:else if apiCallCollectionEnabled}
	<div class="flex flex-wrap gap-3 text-xs text-gray-500 dark:text-gray-400 px-0.5 pb-2">
		<span><span class="text-gray-900 dark:text-gray-300">{apiDashboard.summary.total_calls.toLocaleString()}</span> {$i18n.t('API calls')}</span>
		<span><span class="text-gray-900 dark:text-gray-300">{formatNumber(apiDashboard.summary.input_tokens)}</span> {$i18n.t('Input tokens')}</span>
		<span><span class="text-gray-900 dark:text-gray-300">{formatNumber(apiDashboard.summary.output_tokens)}</span> {$i18n.t('Output tokens')}</span>
		<span><span class="text-gray-900 dark:text-gray-300">{apiDashboard.summary.total_users.toLocaleString()}</span> {$i18n.t('users')}</span>
	</div>

	<div class="mb-4">
		<div class="text-xs font-normal text-gray-600 dark:text-gray-400 mb-2 px-0.5">
			{selectedPeriod === '24h' ? $i18n.t('Hourly API calls') : $i18n.t('Daily API calls')}
		</div>
		{#if apiDashboard.timeline.length > 1}
			<ChartLine
				data={apiDashboard.timeline}
				models={['API calls']}
				colors={['#3b82f6']}
				height={200}
				period={chartPeriods[selectedPeriod] || 'week'}
			/>
		{:else}
			<div class="py-10 text-center text-xs text-gray-400">{$i18n.t('No data')}</div>
		{/if}
	</div>

	<div class="grid md:grid-cols-2 gap-4">
		<div>
			<div class="text-xs font-normal text-gray-700 dark:text-gray-300 mb-1 px-0.5">{$i18n.t('API Routes')}</div>
			<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full">
				<table class="w-full text-xs text-left text-gray-500 dark:text-gray-400 table-auto">
					<thead class="text-xs text-gray-800 uppercase dark:text-gray-200">
						<tr class="border-b-[1.5px] border-gray-50 dark:border-gray-850/30">
							<th scope="col" class="px-2.5 py-2 cursor-pointer" on:click={() => toggleRouteSort('path')}>{$i18n.t('Route')}</th>
							<th scope="col" class="px-2.5 py-2 text-right cursor-pointer" on:click={() => toggleRouteSort('count')}>{$i18n.t('Calls')}</th>
							<th scope="col" class="px-2.5 py-2 text-right cursor-pointer" on:click={() => toggleRouteSort('input_tokens')}>{$i18n.t('Input tokens')}</th>
							<th scope="col" class="px-2.5 py-2 text-right cursor-pointer" on:click={() => toggleRouteSort('output_tokens')}>{$i18n.t('Output tokens')}</th>
						</tr>
					</thead>
					<tbody>
						{#each sortedRoutes as route (`${route.method} ${route.path}`)}
							<tr class="dark:border-gray-850">
								<td class="px-2.5 py-1 font-normal text-gray-900 dark:text-white"><span class="text-gray-400">{route.method}</span> {route.path}</td>
								<td class="px-2.5 py-1 text-right">{route.count.toLocaleString()}</td>
								<td class="px-2.5 py-1 text-right">{formatNumber(route.input_tokens)}</td>
								<td class="px-2.5 py-1 text-right">{formatNumber(route.output_tokens)}</td>
							</tr>
						{:else}
							<tr><td colspan="4" class="px-3 py-2 text-center text-gray-400">{$i18n.t('No data')}</td></tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
		<div>
			<div class="text-xs font-normal text-gray-700 dark:text-gray-300 mb-1 px-0.5">{$i18n.t('User Activity')}</div>
			<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full">
				<table class="w-full text-xs text-left text-gray-500 dark:text-gray-400 table-auto">
					<thead class="text-xs text-gray-800 uppercase dark:text-gray-200">
						<tr class="border-b-[1.5px] border-gray-50 dark:border-gray-850/30">
							<th scope="col" class="px-2.5 py-2 cursor-pointer" on:click={() => toggleApiUserSort('name')}>{$i18n.t('User')}</th>
							<th scope="col" class="px-2.5 py-2 text-right cursor-pointer" on:click={() => toggleApiUserSort('count')}>{$i18n.t('Calls')}</th>
							<th scope="col" class="px-2.5 py-2 text-right cursor-pointer" on:click={() => toggleApiUserSort('input_tokens')}>{$i18n.t('Input tokens')}</th>
							<th scope="col" class="px-2.5 py-2 text-right cursor-pointer" on:click={() => toggleApiUserSort('output_tokens')}>{$i18n.t('Output tokens')}</th>
						</tr>
					</thead>
					<tbody>
						{#each sortedApiUsers as apiUser (apiUser.user_id ?? 'unattributed')}
							<tr class="dark:border-gray-850">
								<td class="px-2.5 py-1 font-normal text-gray-900 dark:text-white">{apiUser.name || apiUser.email || apiUser.user_id || $i18n.t('Unattributed')}</td>
								<td class="px-2.5 py-1 text-right">{apiUser.count.toLocaleString()}</td>
								<td class="px-2.5 py-1 text-right">{formatNumber(apiUser.input_tokens)}</td>
								<td class="px-2.5 py-1 text-right">{formatNumber(apiUser.output_tokens)}</td>
							</tr>
						{:else}
							<tr><td colspan="4" class="px-3 py-2 text-center text-gray-400">{$i18n.t('No data')}</td></tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	</div>
	<div class="text-gray-500 text-xs mt-1.5 text-right">
		ⓘ {$i18n.t('Unattributed calls include unauthenticated requests and earlier records.')}
	</div>
{:else}
<!-- Model Details Modal -->
<AnalyticsModelModal
	bind:show={showModelModal}
	model={selectedModel}
	startDate={getDateRange(selectedPeriod).start}
	endDate={getDateRange(selectedPeriod).end}
/>

<!-- Summary stats -->
	<div class="flex gap-3 text-xs text-gray-500 dark:text-gray-400 px-0.5 pb-2">
		<span
			><span class="font-normal text-gray-900 dark:text-gray-300"
				>{summary.total_messages.toLocaleString()}</span
			>
			{$i18n.t('messages')}</span
		>
		<Tooltip content={$i18n.t('Token counts are estimates and may not reflect actual API usage')}>
			<span class="cursor-help"
				><span class="font-normal text-gray-900 dark:text-gray-300"
					>{formatNumber(totalTokens.total)}</span
				>
				{$i18n.t('tokens')}</span
			>
		</Tooltip>
		<span
			><span class="font-normal text-gray-900 dark:text-gray-300"
				>{summary.total_chats.toLocaleString()}</span
			>
			{$i18n.t('chats')}</span
		>
		<span
			><span class="font-normal text-gray-900 dark:text-gray-300">{summary.total_users}</span>
			{$i18n.t('users')}</span
		>
	</div>

	<!-- Daily usage chart -->
	{#if dailyStats.length > 1}
		{@const allModels = [...new Set(dailyStats.flatMap((d) => Object.keys(d.models || {})))]}
		{@const topModels = allModels.slice(0, 8)}
		{@const chartColors = [
			'#3b82f6',
			'#10b981',
			'#f59e0b',
			'#ef4444',
			'#8b5cf6',
			'#ec4899',
			'#06b6d4',
			'#84cc16'
		]}
		{@const periodMap = { '24h': 'hour', '7d': 'week', '30d': 'month', '90d': 'year', all: 'all' }}
		<div class="mb-4">
			<div class="text-xs font-normal text-gray-600 dark:text-gray-400 mb-2 px-0.5">
				{selectedPeriod === '24h' ? $i18n.t('Hourly Messages') : $i18n.t('Daily Messages')}
			</div>
			<ChartLine
				data={dailyStats}
				models={topModels}
				colors={chartColors}
				height={200}
				period={periodMap[selectedPeriod] || 'week'}
			/>
		</div>
	{/if}
	<div class="grid md:grid-cols-2 gap-4">
		<!-- Model Usage Table -->
		<div>
			<div class="text-xs font-normal text-gray-700 dark:text-gray-300 mb-1 px-0.5">
				{$i18n.t('Model Usage')}
			</div>
			<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full">
				<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto">
					<thead class="text-xs text-gray-800 uppercase bg-transparent dark:text-gray-200">
						<tr class="border-b-[1.5px] border-gray-50 dark:border-gray-850/30">
							<th scope="col" class="px-2.5 py-2 w-8">#</th>
							<th
								scope="col"
								class="px-2.5 py-2 cursor-pointer select-none"
								on:click={() => toggleModelSort('name')}
							>
								<div class="flex gap-1.5 items-center">
									{$i18n.t('Model')}
									{#if modelOrderBy === 'name'}
										<span class="font-normal">
											{#if modelDirection === 'asc'}<ChevronUp
													className="size-2"
												/>{:else}<ChevronDown className="size-2" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-2" /></span>
									{/if}
								</div>
							</th>
							<th
								scope="col"
								class="px-2.5 py-2 cursor-pointer select-none text-right"
								on:click={() => toggleModelSort('count')}
							>
								<div class="flex gap-1.5 items-center justify-end">
									{$i18n.t('Messages')}
									{#if modelOrderBy === 'count'}
										<span class="font-normal">
											{#if modelDirection === 'asc'}<ChevronUp
													className="size-2"
												/>{:else}<ChevronDown className="size-2" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-2" /></span>
									{/if}
								</div>
							</th>
							<th
								scope="col"
								class="px-2.5 py-2 cursor-pointer select-none text-right"
								on:click={() => toggleModelSort('users')}
							>
								<div class="flex gap-1.5 items-center justify-end">
									{$i18n.t('Users')}
									{#if modelOrderBy === 'users'}
										<span class="font-normal">
											{#if modelDirection === 'asc'}<ChevronUp
													className="size-2"
												/>{:else}<ChevronDown className="size-2" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-2" /></span>
									{/if}
								</div>
							</th>
							<th
								scope="col"
								class="px-2.5 py-2 cursor-pointer select-none text-right"
								on:click={() => toggleModelSort('chats')}
							>
								<div class="flex gap-1.5 items-center justify-end">
									{$i18n.t('Chats')}
									{#if modelOrderBy === 'chats'}
										<span class="font-normal">
											{#if modelDirection === 'asc'}<ChevronUp
													className="size-2"
												/>{:else}<ChevronDown className="size-2" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-2" /></span>
									{/if}
								</div>
							</th>
							<th
								scope="col"
								class="px-2.5 py-2 cursor-pointer select-none text-right"
								on:click={() => toggleModelSort('tokens')}
							>
								<div class="flex gap-1.5 items-center justify-end">
									{$i18n.t('Tokens')}
									{#if modelOrderBy === 'tokens'}
										<span class="font-normal">
											{#if modelDirection === 'asc'}<ChevronUp
													className="size-2"
												/>{:else}<ChevronDown className="size-2" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-2" /></span>
									{/if}
								</div>
							</th>
							<th
								scope="col"
								class="px-2.5 py-2 cursor-pointer select-none text-right w-16"
								on:click={() => toggleModelSort('percentage')}
							>
								<div class="flex gap-1.5 items-center justify-end">
									%
									{#if modelOrderBy === 'percentage'}
										<span class="font-normal">
											{#if modelDirection === 'asc'}<ChevronUp
													className="size-2"
												/>{:else}<ChevronDown className="size-2" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-2" /></span>
									{/if}
								</div>
							</th>
						</tr>
					</thead>
					<tbody>
						{#each sortedModels as model, idx (model.model_id)}
							<tr
								class="dark:border-gray-850 text-xs cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
								on:click={() => {
									selectedModel = { id: model.model_id, name: model.name };
									showModelModal = true;
								}}
							>
								<td class="px-3 py-1 text-gray-400">{idx + 1}</td>
								<td class="px-3 py-1 font-normal text-gray-900 dark:text-white">
									<div class="flex items-center gap-2">
										<img
											src="{WEBUI_API_BASE_URL}/models/model/profile/image?id={model.model_id}"
											alt={model.name}
											class="size-5 rounded-full object-cover shrink-0"
											on:error={(e) => {
												// LICENSE covers this Open WebUI fallback logo.
												// Do not alter, remove, obscure, or replace it except as LICENSE permits:
												// https://docs.openwebui.com/license.
												e.target.src = '/favicon.png';
											}}
										/>
										<span class="truncate max-w-[9.375rem]">{model.name}</span>
									</div>
								</td>
								<td class="px-3 py-1 text-right">{model.count.toLocaleString()}</td>
								<td class="px-3 py-1 text-right">{(model.unique_users ?? 0).toLocaleString()}</td>
								<td class="px-3 py-1 text-right">{(model.unique_chats ?? 0).toLocaleString()}</td>
								<td class="px-3 py-1 text-right"
									>{formatNumber(tokenStats[model.model_id]?.total_tokens ?? 0)}</td
								>
								<td class="px-3 py-1 text-right text-gray-400">
									{totalModelMessages > 0
										? ((model.count / totalModelMessages) * 100).toFixed(1)
										: 0}%
								</td>
							</tr>
						{/each}
						{#if sortedModels.length === 0}
							<tr
								><td colspan="7" class="px-3 py-2 text-center text-gray-400"
									>{$i18n.t('No data')}</td
								></tr
							>
						{/if}
					</tbody>
				</table>
			</div>
		</div>

		<!-- User Activity Table -->
		<div>
			<div class="text-xs font-normal text-gray-700 dark:text-gray-300 mb-1 px-0.5">
				{$i18n.t('User Activity')}
			</div>
			<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full">
				<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto">
					<thead class="text-xs text-gray-800 uppercase bg-transparent dark:text-gray-200">
						<tr class="border-b-[1.5px] border-gray-50 dark:border-gray-850/30">
							<th scope="col" class="px-2.5 py-2 w-8">#</th>
							<th
								scope="col"
								class="px-2.5 py-2 cursor-pointer select-none"
								on:click={() => toggleUserSort('name')}
							>
								<div class="flex gap-1.5 items-center">
									{$i18n.t('User')}
									{#if userOrderBy === 'name'}
										<span class="font-normal">
											{#if userDirection === 'asc'}<ChevronUp
													className="size-2"
												/>{:else}<ChevronDown className="size-2" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-2" /></span>
									{/if}
								</div>
							</th>
							<th
								scope="col"
								class="px-2.5 py-2 cursor-pointer select-none text-right"
								on:click={() => toggleUserSort('count')}
							>
								<div class="flex gap-1.5 items-center justify-end">
									{$i18n.t('Messages')}
									{#if userOrderBy === 'count'}
										<span class="font-normal">
											{#if userDirection === 'asc'}<ChevronUp
													className="size-2"
												/>{:else}<ChevronDown className="size-2" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-2" /></span>
									{/if}
								</div>
							</th>
							<th
								scope="col"
								class="px-2.5 py-2 cursor-pointer select-none text-right"
								on:click={() => toggleUserSort('tokens')}
							>
								<div class="flex gap-1.5 items-center justify-end">
									{$i18n.t('Tokens')}
									{#if userOrderBy === 'tokens'}
										<span class="font-normal">
											{#if userDirection === 'asc'}<ChevronUp
													className="size-2"
												/>{:else}<ChevronDown className="size-2" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-2" /></span>
									{/if}
								</div>
							</th>
						</tr>
					</thead>
					<tbody>
						{#each sortedUsers as user, idx (user.user_id)}
							<tr class="dark:border-gray-850 text-xs">
								<td class="px-3 py-1 text-gray-400">{idx + 1}</td>
								<td class="px-3 py-1 font-normal text-gray-900 dark:text-white">
									<div class="flex items-center gap-2">
										<img
											src="{WEBUI_API_BASE_URL}/users/{user.user_id}/profile/image"
											alt={user.name || 'User'}
											class="size-5 rounded-full object-cover shrink-0"
											on:error={(e) => {
												e.target.src = '/user.png';
											}}
										/>
										<span class="truncate max-w-[9.375rem]"
											>{user.name || user.email || user.user_id.substring(0, 8)}</span
										>
									</div>
								</td>
								<td class="px-3 py-1 text-right">{user.count.toLocaleString()}</td>
								<td class="px-3 py-1 text-right">{formatNumber(user.total_tokens ?? 0)}</td>
							</tr>
						{/each}
						{#if sortedUsers.length === 0}
							<tr
								><td colspan="4" class="px-3 py-2 text-center text-gray-400"
									>{$i18n.t('No data')}</td
								></tr
							>
						{/if}
					</tbody>
				</table>
			</div>
		</div>
	</div>

	<div class="text-gray-500 text-xs mt-1.5 text-right">
		ⓘ {$i18n.t('Message counts are based on assistant responses.')}
	</div>
{/if}
