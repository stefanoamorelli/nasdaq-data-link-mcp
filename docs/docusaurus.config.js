// @ts-check
// `@type` JSDoc annotations allow editor autocompletion and type checking
// (when paired with `@ts-check`).

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Nasdaq Data Link MCP',
  tagline: 'MCP server for accessing Nasdaq Data Link financial and economic datasets',
  favicon: 'img/favicon.ico',

  // Set the production url of your site here
  url: 'https://stefanoamorelli.github.io',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For GitHub pages deployment, it is often '/<projectName>/'
  baseUrl: '/nasdaq-data-link-mcp/',

  // GitHub pages deployment config.
  // If you aren't using GitHub pages, you don't need these.
  organizationName: 'stefanoamorelli', // Usually your GitHub org/user name.
  projectName: 'nasdaq-data-link-mcp', // Usually your repo name.
  trailingSlash: false,

  onBrokenLinks: 'warn',
  onBrokenMarkdownLinks: 'warn',

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },
  
  // We don't need redirects anymore since we use index.md directly
  plugins: [],

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          path: 'docs',
          sidebarPath: './sidebars.js',
          // Please change this to your repo.
          // Remove this to remove the "edit this page" links.
          editUrl:
            'https://github.com/stefanoamorelli/nasdaq-data-link-mcp/tree/main/docs/',
          routeBasePath: '/', // Make docs the homepage
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      // Replace with your project's social card
      image: 'img/social-card.jpg',
      navbar: {
        title: 'Nasdaq Data Link MCP',
        logo: {
          alt: 'Nasdaq Data Link MCP Logo',
          src: 'img/logo.svg',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'tutorialSidebar',
            position: 'left',
            label: 'Documentation',
          },
          {
            href: 'https://github.com/stefanoamorelli/nasdaq-data-link-mcp',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              {
                label: 'Installation',
                to: '/installation',
              },
              {
                label: 'Tools',
                to: '/tools',
              },
            ],
          },
          {
            title: 'More',
            items: [
              {
                label: 'GitHub',
                href: 'https://github.com/stefanoamorelli/nasdaq-data-link-mcp',
              },
              {
                label: 'Nasdaq Data Link',
                href: 'https://data.nasdaq.com/',
              },
            ],
          },
        ],
        copyright: `Copyright © ${new Date().getFullYear()} Stefano Amorelli. Built with Docusaurus.`,
      },
      prism: {
        theme: require('prism-react-renderer').themes.github,
        darkTheme: require('prism-react-renderer').themes.dracula,
      },
    }),
};

module.exports = config;