import React from 'react';
import clsx from 'clsx';
import styles from './styles.module.css';

const FeatureList = [
  {
    title: 'World Bank Data',
    description: (
      <>
        Access global economic indicators from the World Bank dataset on Nasdaq Data Link, 
        freely available for personal use.
      </>
    ),
  },
  {
    title: 'Retail Trading Activity',
    description: (
      <>
        Explore Nasdaq RTAT data with preview available for free and full data under subscription.
      </>
    ),
  },
  {
    title: 'Equities 360',
    description: (
      <>
        Get company statistics and fundamental data through Equities 360.
      </>
    ),
  },
];

function Feature({title, description}) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center padding-horiz--md">
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures() {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}