/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Steps, Tag } from 'antd';
import Setup1 from './Ext3Setup1';
import Setup2 from './Ext3Setup2';
import Setup3 from './Ext3Setup3';
import Setup4 from './Ext3Setup4';
import store from './store';
import styles from './index.module.css';
import tagStore from 'pages/config/tag/store';

export default observer(function Ext1From() {
  const appName = store.currentRecord.name;
  let title = `容器发布 - 【${appName}】`;
  if (store.deploy.id) {
    store.isReadOnly ? title = '查看' + title : title = '编辑' + title;
  } else {
    title = '新建' + title
  }

  const appTags = tagStore.records

  return (
    <Modal
      visible
      width={800}
      maskClosable={false}
      title={
        <div>
          {store.deploy.env_name ? <Tag color="#108ee9">{store.deploy.env_name}</Tag> : null}
          {title}
          {store.deploy.app_rel_tags?.length > 0 ? store.deploy.app_rel_tags.map(tid => (
              <Tag style={{ border: 'none' }} color="orange" key={`tag-${tid}`}>{appTags.find(item => item.id === tid).name}</Tag>
            )) : null}
          {store.deploy.env_prod ? <Tag color="#f50">生产环境</Tag> : null}
        </div>
      }
      onCancel={() => store.ext3Visible = false}
      footer={null}>
      <Steps current={store.page} className={styles.steps}>
        <Steps.Step key={0} title="基本配置"/>
        <Steps.Step key={1} title="构建配置"/>
        <Steps.Step key={2} title="镜像配置"/>
        <Steps.Step key={3} title="发布配置"/>
      </Steps>
      {store.page === 0 && <Setup1/>}
      {store.page === 1 && <Setup2/>}
      {store.page === 2 && <Setup3/>}
      {store.page === 3 && <Setup4/>}
    </Modal>
  )
})
