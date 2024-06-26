/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { DeleteOutlined } from '@ant-design/icons';
import { Select, DatePicker, Space } from 'antd';
import { SearchForm, AuthDiv, AuthButton, Breadcrumb, AppSelector } from 'components';
import Ext1Form from './Ext1Form';
import Ext2Form from './Ext2Form';
import Ext3Form from './Ext3Form';
import RestartFrom from './RestartFrom';
import Approve from './Approve';
import ComTable from './Table';
import Ext1Console from './Ext1Console';
import Ext2Console from './Ext2Console';
import Ext3Console from './Ext3Console';
import BatchDelete from './BatchDelete';
import Rollback from './Rollback';
import { includes } from 'libs';
import envStore from 'pages/config/environment/store';
import appStore from 'pages/config/app/store';
import tagStore from 'pages/config/tag/store';
import store from './store';
import moment from 'moment';
import styles from './index.module.less';

function Index() {
  useEffect(() => {
    store.fetchRecords()
    if (envStore.records.length === 0) envStore.fetchRecords()
    if (appStore.records.length === 0) appStore.fetchRecords()
    if (tagStore.records.length === 0) tagStore.fetchRecords()
    return () => store.leaveConsole()
  }, [])

  const tags = tagStore.records || []

  return (
    <AuthDiv auth="deploy.request.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>应用发布</Breadcrumb.Item>
        <Breadcrumb.Item>发布申请</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={7} title="标签">
          <Select allowClear value={store.f_tag} onChange={e => store.f_tag = e} placeholder="请选择">
            { tags.map(item => (
              <Select.Option key={item.id} value={item.id}>
                <span>{item.name}</span>
              </Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={7} title="发布环境">
          <Select
            allowClear
            showSearch
            value={store.f_env_id}
            filterOption={(i, o) => includes(o.children, i)}
            onChange={v => store.f_env_id = v}
            placeholder="请选择">
            {envStore.records.map(item => (
              <Select.Option key={item.id} value={item.id}>{item.name}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={7} title="应用名称">
          <Select
            allowClear
            showSearch
            value={store.f_app_id}
            filterOption={(i, o) => includes(o.children, i)}
            onChange={v => store.f_app_id = v}
            placeholder="请选择">
            {appStore.records.map(item => (
              <Select.Option key={item.id} value={item.id}>{item.name}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={8} title="时间">
          <DatePicker.RangePicker
            value={store.f_s_date ? [moment(store.f_s_date), moment(store.f_e_date)] : undefined}
            onChange={store.updateDate}/>
        </SearchForm.Item>
        <SearchForm.Item span={4} style={{textAlign: 'right'}}>
          <AuthButton
            auth="deploy.request.del"
            type="danger"
            icon={<DeleteOutlined/>}
            onClick={() => store.batchVisible = true}>批量删除</AuthButton>
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      <AppSelector
        visible={store.addVisible}
        restart={store.filterRestartVisble}
        onCancel={() => {store.addVisible = false; store.filterRestartVisble = false;}}
        onSelect={store.confirmAdd}/>
      {store.ext1Visible && <Ext1Form/>}
      {store.ext2Visible && <Ext2Form/>}
      {store.ext3Visible && <Ext3Form/>}
      {store.restartVisble && <RestartFrom/>}
      {store.batchVisible && <BatchDelete/>}
      {store.approveVisible && <Approve/>}
      {store.rollbackVisible && <Rollback/>}
      {store.tabs.length > 0 && (
        <Space className={styles.miniConsole}>
          {store.tabs.map(item => item.id ?
            (item.app_extend === '1' ? (
              <Ext1Console key={item.id} request={item}/>
            ) : 
            (item.app_extend === '3' ? (
              <Ext3Console key={item.id} request={item}/>
            ) : (
              <Ext2Console key={item.id} request={item}/>
            )))
            : null
            )}
        </Space>
      )}
    </AuthDiv>
  )
}

export default observer(Index)