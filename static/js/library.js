// library.js - Library browsing and video selection module
(function() {
    'use strict';
    var S = window.PartyState;

    function saveLibraryState(state) {
        try {
            localStorage.setItem(S.LIBRARY_STATE_KEY, JSON.stringify(state));
        } catch (e) {
            console.warn('Could not save library state to localStorage');
        }
    }

    function getSavedLibraryState() {
        try {
            var saved = localStorage.getItem(S.LIBRARY_STATE_KEY);
            return saved ? JSON.parse(saved) : null;
        } catch (e) {
            console.warn('Could not load library state from localStorage');
            return null;
        }
    }

    function clearLibraryState() {
        try {
            localStorage.removeItem(S.LIBRARY_STATE_KEY);
        } catch (e) {
            console.warn('Could not clear library state from localStorage');
        }
    }

    async function restoreLibraryState() {
        var savedState = getSavedLibraryState();

        if (!savedState) {
            loadLibraries();
            return;
        }

        console.log('Restoring library state:', savedState);

        try {
            if (savedState.type === 'episodes' && savedState.seasonId) {
                await loadSeasonEpisodes(savedState.seasonId, savedState.seasonName, savedState.seriesName);
            } else if (savedState.type === 'seasons' && savedState.seriesId) {
                await loadSeriesSeasons(savedState.seriesId, savedState.seriesName);
            } else if (savedState.type === 'library' && savedState.libraryId) {
                await loadItemsFromLibrary(savedState.libraryId);
            } else {
                loadLibraries();
            }
        } catch (error) {
            console.warn('Failed to restore library state, loading libraries:', error);
            loadLibraries();
        }
    }

    async function loadLibraries() {
        try {
            S.dom.libraryContent.innerHTML = '<p>Loading libraries...</p>';
            clearLibraryState();

            var response = await fetch(S.appPrefix + '/api/libraries');
            var data = await response.json();

            if (data.Items && data.Items.length > 0) {
                S.dom.libraryContent.innerHTML = '';
                data.Items.forEach(function(library) {
                    var item = createLibraryItem(library, function() {
                        loadItemsFromLibrary(library.Id);
                    });
                    S.dom.libraryContent.appendChild(item);
                });
            } else {
                S.dom.libraryContent.innerHTML = '<p>No libraries found</p>';
            }
        } catch (error) {
            S.dom.libraryContent.innerHTML = '<p>Error loading libraries</p>';
        }
    }

    async function loadItemsFromLibrary(parentId) {
        try {
            S.dom.libraryContent.innerHTML = '<p>Loading items...</p>';
            saveLibraryState({ type: 'library', libraryId: parentId });

            var response = await fetch(S.appPrefix + '/api/items?parentId=' + parentId + '&recursive=true');
            var data = await response.json();
            displayItems(data.Items, 'library');
        } catch (error) {
            S.dom.libraryContent.innerHTML = '<p>Error loading items</p>';
        }
    }

    async function loadSeriesSeasons(seriesId, seriesName) {
        try {
            S.dom.libraryContent.innerHTML = '<p>Loading seasons...</p>';
            saveLibraryState({ type: 'seasons', seriesId: seriesId, seriesName: seriesName });

            var response = await fetch(S.appPrefix + '/api/items?parentId=' + seriesId + '&recursive=false');
            var data = await response.json();

            S.dom.libraryContent.innerHTML = '';

            var backBtn = document.createElement('div');
            backBtn.className = 'library-item';
            backBtn.style.background = '#667eea';
            backBtn.style.cursor = 'pointer';
            backBtn.innerHTML = '<div class="library-item-info"><div class="library-item-title">\u2190 Back</div><div class="library-item-meta">Return to library</div></div>';
            backBtn.addEventListener('click', function() {
                loadLibraries();
            });
            S.dom.libraryContent.appendChild(backBtn);

            var titleDiv = document.createElement('div');
            titleDiv.style.padding = '1rem';
            titleDiv.style.color = '#667eea';
            titleDiv.style.fontWeight = 'bold';
            titleDiv.style.fontSize = '1.1rem';
            titleDiv.textContent = seriesName;
            S.dom.libraryContent.appendChild(titleDiv);

            var items = data.Items || [];
            if (items.length > 0 && items[0].Type === 'Season') {
                displayItems(items, 'seasons', seriesName);
            } else {
                displayItems(items, 'episodes');
            }
        } catch (error) {
            S.dom.libraryContent.innerHTML = '<p>Error loading seasons</p>';
        }
    }

    async function loadSeasonEpisodes(seasonId, seasonName, seriesName, seriesId) {
        try {
            S.dom.libraryContent.innerHTML = '<p>Loading episodes...</p>';
            saveLibraryState({ type: 'episodes', seasonId: seasonId, seasonName: seasonName, seriesName: seriesName });

            var response = await fetch(S.appPrefix + '/api/items?parentId=' + seasonId + '&recursive=false');
            var data = await response.json();

            S.currentEpisodeList = data.Items || [];
            S.currentSeasonId = seasonId;
            S.currentSeriesName = seriesName;

            if (!seriesId) {
                try {
                    var seasonResponse = await fetch(S.appPrefix + '/api/item/' + seasonId);
                    var seasonData = await seasonResponse.json();
                    S.currentSeriesId = seasonData.SeriesId || null;
                } catch (e) {
                    S.currentSeriesId = null;
                }
            } else {
                S.currentSeriesId = seriesId;
            }

            S.dom.libraryContent.innerHTML = '';

            var backBtn = document.createElement('div');
            backBtn.className = 'library-item';
            backBtn.style.background = '#667eea';
            backBtn.style.cursor = 'pointer';
            backBtn.innerHTML = '<div class="library-item-info"><div class="library-item-title">\u2190 Back to Seasons</div><div class="library-item-meta">Return to ' + seriesName + '</div></div>';
            backBtn.addEventListener('click', function() {
                fetch(S.appPrefix + '/api/item/' + seasonId)
                    .then(function(res) { return res.json(); })
                    .then(function(season) {
                        if (season.SeriesId) {
                            loadSeriesSeasons(season.SeriesId, seriesName);
                        } else {
                            loadLibraries();
                        }
                    })
                    .catch(function() { loadLibraries(); });
            });
            S.dom.libraryContent.appendChild(backBtn);

            var titleDiv = document.createElement('div');
            titleDiv.style.padding = '1rem';
            titleDiv.style.color = '#667eea';
            titleDiv.style.fontWeight = 'bold';
            titleDiv.style.fontSize = '1.1rem';
            titleDiv.textContent = seriesName + ' - ' + seasonName;
            S.dom.libraryContent.appendChild(titleDiv);

            displayItems(data.Items, 'episodes');
        } catch (error) {
            S.dom.libraryContent.innerHTML = '<p>Error loading episodes</p>';
        }
    }

    async function loadItems(itemType) {
        try {
            S.dom.libraryContent.innerHTML = '<p>Loading items...</p>';
            var response = await fetch(S.appPrefix + '/api/items?type=' + itemType + '&recursive=true');
            var data = await response.json();
            displayItems(data.Items);
        } catch (error) {
            S.dom.libraryContent.innerHTML = '<p>Error loading items</p>';
        }
    }

    function displayItems(items, context, seriesName) {
        if (items && items.length > 0) {
            S.dom.libraryContent.innerHTML = '';

            var displayableItems;
            if (context === 'library') {
                displayableItems = items.filter(function(item) {
                    return item.Type === 'Movie' || item.Type === 'Series' || item.Type === 'Video';
                });
            } else if (context === 'seasons') {
                displayableItems = items.filter(function(item) {
                    return item.Type === 'Season';
                });
            } else {
                displayableItems = items.filter(function(item) {
                    return item.Type === 'Movie' || item.Type === 'Episode' || item.Type === 'Video';
                });
            }

            if (displayableItems.length > 0) {
                displayableItems.forEach(function(item) {
                    var itemEl = createLibraryItem(item, function() {
                        if (item.Type === 'Series') {
                            loadSeriesSeasons(item.Id, item.Name);
                        } else if (item.Type === 'Season') {
                            loadSeasonEpisodes(item.Id, item.Name, seriesName);
                        } else {
                            selectVideo(item);
                        }
                    }, true);
                    S.dom.libraryContent.appendChild(itemEl);
                });
            } else {
                S.dom.libraryContent.innerHTML = '<p>No items found</p>';
            }
        } else {
            S.dom.libraryContent.innerHTML = '<p>No items found</p>';
        }
    }

    function createLibraryItem(item, onClick, showImage) {
        var div = document.createElement('div');
        div.className = 'library-item';
        div.addEventListener('click', onClick);

        if (showImage && item.Id) {
            var img = document.createElement('img');
            img.src = S.appPrefix + '/api/image/' + item.Id + '?type=Primary';
            img.loading = 'lazy';
            img.onerror = function() {
                img.style.display = 'none';
            };
            div.appendChild(img);
        }

        var info = document.createElement('div');
        info.className = 'library-item-info';

        var title = document.createElement('div');
        title.className = 'library-item-title';
        title.textContent = item.Name;

        var meta = document.createElement('div');
        meta.className = 'library-item-meta';

        if (item.Type) {
            meta.textContent = item.Type;
        }

        if (item.ProductionYear) {
            meta.textContent += ' \u2022 ' + item.ProductionYear;
        }

        info.appendChild(title);
        if (meta.textContent) {
            info.appendChild(meta);
        }

        div.appendChild(info);
        return div;
    }

    function selectVideo(item) {
        window.PartyChat.addSystemMessage(S.username + ' selected ' + item.Name);

        S.socket.emit('toggle_library', {
            party_id: S.partyId,
            show: false
        });

        if (item.Type === 'Episode' && S.currentEpisodeList.length > 0) {
            S.currentEpisodeIndex = S.currentEpisodeList.findIndex(function(ep) { return ep.Id === item.Id; });
            console.log('Selected episode ' + (S.currentEpisodeIndex + 1) + ' of ' + S.currentEpisodeList.length);
        } else {
            S.currentEpisodeIndex = -1;
            S.currentEpisodeList = [];
            S.currentSeasonId = null;
            S.currentSeriesId = null;
        }

        S.socket.emit('select_video', {
            party_id: S.partyId,
            item_id: item.Id,
            item_name: item.Name,
            item_overview: item.Overview || ''
        });

        S.canStopVideo = true;
    }

    async function performSearch(query) {
        try {
            S.dom.libraryContent.innerHTML = '<p>Searching...</p>';

            var response = await fetch(S.appPrefix + '/api/search?q=' + encodeURIComponent(query));
            var data = await response.json();

            S.dom.libraryContent.innerHTML = '';

            var headerDiv = document.createElement('div');
            headerDiv.style.padding = '1rem';
            headerDiv.style.color = '#667eea';
            headerDiv.style.fontWeight = 'bold';
            headerDiv.style.fontSize = '1.1rem';
            headerDiv.textContent = 'Search results for "' + query + '"';
            S.dom.libraryContent.appendChild(headerDiv);

            if (data.Items && data.Items.length > 0) {
                displayItems(data.Items, 'library');
            } else {
                var noResults = document.createElement('p');
                noResults.textContent = 'No results found';
                noResults.style.padding = '1rem';
                noResults.style.color = '#aaa';
                S.dom.libraryContent.appendChild(noResults);
            }
        } catch (error) {
            S.dom.libraryContent.innerHTML = '<p>Error performing search</p>';
        }
    }

    function init() {
        // Navigation buttons
        S.dom.navBtns.forEach(function(btn) {
            btn.addEventListener('click', function() {
                S.dom.navBtns.forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');

                var type = btn.dataset.type;
                if (type === 'libraries') {
                    loadLibraries();
                } else if (type === 'movies') {
                    loadItems('Movie');
                } else if (type === 'shows') {
                    loadItems('Series');
                }
            });
        });

        // Search input listeners
        if (S.dom.searchInput) {
            S.dom.searchInput.addEventListener('input', function(e) {
                var query = e.target.value.trim();

                if (S.dom.clearSearchBtn) {
                    S.dom.clearSearchBtn.style.display = query ? 'flex' : 'none';
                }

                clearTimeout(S.searchTimeout);
                S.searchTimeout = setTimeout(function() {
                    if (query.length >= 2) {
                        performSearch(query);
                    } else if (query.length === 0) {
                        loadLibraries();
                    }
                }, 300);
            });

            S.dom.searchInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    var query = e.target.value.trim();
                    if (query.length >= 2) {
                        clearTimeout(S.searchTimeout);
                        performSearch(query);
                    }
                }
            });
        }

        if (S.dom.clearSearchBtn) {
            S.dom.clearSearchBtn.addEventListener('click', function() {
                S.dom.searchInput.value = '';
                S.dom.clearSearchBtn.style.display = 'none';
                loadLibraries();
                S.dom.searchInput.focus();
            });
        }
    }

    window.PartyLibrary = {
        init: init,
        loadLibraries: loadLibraries,
        selectVideo: selectVideo,
        restoreLibraryState: restoreLibraryState
    };
})();
