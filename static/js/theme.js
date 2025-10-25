// Theme Management
(function() {
    'use strict';

    const THEME_STORAGE_KEY = 'emby-watchparty-theme';
    const DEFAULT_THEME = 'cyberpunk';

    // Get saved theme or default
    function getSavedTheme() {
        try {
            return localStorage.getItem(THEME_STORAGE_KEY) || DEFAULT_THEME;
        } catch (e) {
            console.warn('localStorage not available, using default theme');
            return DEFAULT_THEME;
        }
    }

    // Save theme to localStorage
    function saveTheme(theme) {
        try {
            localStorage.setItem(THEME_STORAGE_KEY, theme);
        } catch (e) {
            console.warn('Could not save theme to localStorage');
        }
    }

    // Material Design vibrant color palette
    const materialColors = [
        '#f44336', '#e91e63', '#9c27b0', '#673ab7', '#3f51b5',
        '#2196f3', '#03a9f4', '#00bcd4', '#009688', '#4caf50',
        '#8bc34a', '#cddc39', '#ffeb3b', '#ffc107', '#ff9800',
        '#ff5722', '#795548', '#607d8b', '#e91e63', '#9c27b0'
    ];

    // Generate random Material Design gradient
    function generateMaterialGradient() {
        const color1 = materialColors[Math.floor(Math.random() * materialColors.length)];
        let color2 = materialColors[Math.floor(Math.random() * materialColors.length)];

        // Ensure colors are different
        while (color2 === color1) {
            color2 = materialColors[Math.floor(Math.random() * materialColors.length)];
        }

        return { primary: color1, secondary: color2 };
    }

    // Apply Material Design random gradients
    function applyMaterialGradients() {
        const gradient = generateMaterialGradient();

        // Apply random colors as CSS variables to body element
        document.body.style.setProperty('--cyber-primary', gradient.primary);
        document.body.style.setProperty('--cyber-secondary', gradient.secondary);

        // Generate complementary colors
        const accent = materialColors[Math.floor(Math.random() * materialColors.length)];
        const gold = materialColors[Math.floor(Math.random() * materialColors.length)];

        document.body.style.setProperty('--cyber-accent', accent);
        document.body.style.setProperty('--cyber-gold', gold);

        // Update shadow glow to use new primary color
        const primaryRgb = hexToRgb(gradient.primary);
        document.body.style.setProperty('--shadow-glow', `0 0 20px ${gradient.primary}`);
        document.body.style.setProperty('--shadow-theater', `0 0 30px ${gradient.primary}`);

        console.log(`🎨 Material gradients: ${gradient.primary} → ${gradient.secondary}, accent: ${accent}, gold: ${gold}`);
    }

    // Helper function to convert hex to rgb
    function hexToRgb(hex) {
        const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
        return result ? {
            r: parseInt(result[1], 16),
            g: parseInt(result[2], 16),
            b: parseInt(result[3], 16)
        } : null;
    }

    // Clear Material Design inline styles
    function clearMaterialStyles() {
        document.body.style.removeProperty('--cyber-primary');
        document.body.style.removeProperty('--cyber-secondary');
        document.body.style.removeProperty('--cyber-accent');
        document.body.style.removeProperty('--cyber-gold');
        document.body.style.removeProperty('--shadow-glow');
        document.body.style.removeProperty('--shadow-theater');
    }

    // Apply theme to body
    function applyTheme(theme) {
        document.body.setAttribute('data-theme', theme);

        // If Material theme, apply random gradients
        if (theme === 'material') {
            applyMaterialGradients();
        } else {
            // Clear Material inline styles when switching to other themes
            clearMaterialStyles();
        }

        // Update all theme selectors on the page
        const selectors = document.querySelectorAll('#themeSelector');
        selectors.forEach(selector => {
            selector.value = theme;
        });

        console.log(`Theme applied: ${theme}`);
    }

    // Initialize theme on page load
    function initTheme() {
        const savedTheme = getSavedTheme();
        applyTheme(savedTheme);
    }

    // Setup theme selector listeners
    function setupThemeSelector() {
        const selectors = document.querySelectorAll('#themeSelector');

        selectors.forEach(selector => {
            selector.addEventListener('change', function(e) {
                const newTheme = e.target.value;
                applyTheme(newTheme);
                saveTheme(newTheme);
            });
        });
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            initTheme();
            setupThemeSelector();
        });
    } else {
        initTheme();
        setupThemeSelector();
    }

    // Export for potential external use
    window.ThemeManager = {
        applyTheme,
        getSavedTheme,
        saveTheme,
        randomizeMaterialColors: applyMaterialGradients
    };

    // Add "Randomize" button next to Material theme selector
    function addRandomizeButton() {
        const selectors = document.querySelectorAll('#themeSelector');
        selectors.forEach(selector => {
            // Check if button already exists
            if (selector.parentElement.querySelector('.randomize-btn')) {
                return;
            }

            const randomizeBtn = document.createElement('button');
            randomizeBtn.className = 'btn-small randomize-btn';
            randomizeBtn.textContent = '🎲 Randomize';
            randomizeBtn.style.marginLeft = '0.5rem';
            randomizeBtn.style.display = 'none'; // Hidden by default

            randomizeBtn.addEventListener('click', function(e) {
                e.preventDefault();
                if (document.body.getAttribute('data-theme') === 'material') {
                    applyMaterialGradients();
                }
            });

            selector.parentElement.appendChild(randomizeBtn);

            // Show/hide randomize button based on theme
            selector.addEventListener('change', function() {
                const isMaterial = selector.value === 'material';
                randomizeBtn.style.display = isMaterial ? 'inline-block' : 'none';
            });

            // Set initial visibility
            const currentTheme = selector.value || getSavedTheme();
            randomizeBtn.style.display = currentTheme === 'material' ? 'inline-block' : 'none';
        });
    }

    // Add randomize button after theme selector is set up
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(addRandomizeButton, 100);
        });
    } else {
        setTimeout(addRandomizeButton, 100);
    }
})();
