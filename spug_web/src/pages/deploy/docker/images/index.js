/**
 * Copyright: (c) ccx0lw. https://github.com/ccx0lw/spug
 * Copyright: (c) <fcjava@163.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Select } from 'antd';
import { SearchForm, AuthDiv, Breadcrumb, AppSelector } from 'components';
import { includes } from 'libs';
import ComTable from './Table';
import ComForm from './Form';
import Console from './Console';
import Detail from './Detail';
import store from './store';
import envStore from 'pages/config/environment/store';
import appStore from 'pages/config/app/store';
import tagStore from 'pages/config/tag/store';

export default observer(function () {
  useEffect(() => {
    store.fetchRecords();
    if (!appStore.records.length) appStore.fetchRecords()
    if (!envStore.records.length) envStore.fetchRecords()
    if (!tagStore.records.length) tagStore.fetchRecords()
  }, [])

  const tags = tagStore.records || []

  return (
    <AuthDiv auth="deploy.docker_image.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>应用发布</Breadcrumb.Item>
        <Breadcrumb.Item>容器镜像</Breadcrumb.Item>
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
        <SearchForm.Item span={6} title="应用">
          <Select
            allowClear
            showSearch
            value={store.f_app_id}
            onChange={v => store.f_app_id = v}
            filterOption={(i, o) => includes(o.children, i)}
            placeholder="请选择">
            {appStore.records.map(item => (
              <Select.Option key={item.id} value={item.id}>{item.name}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="环境">
          <Select
            allowClear
            showSearch
            value={store.f_env_id}
            onChange={v => store.f_env_id = v}
            filterOption={(i, o) => includes(o.children, i)}
            placeholder="请选择">
            {envStore.records.map(item => (
              <Select.Option key={item.id} value={item.type}>{item.name}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      {store.addVisible && (
        <AppSelector
        visible
        filter={item => item.extend === '3'}
        onCancel={() => store.addVisible = false}
        onSelect={store.confirmAdd}/>
      )}

      <Detail visible={store.detailVisible}/>
      {store.formVisible && <ComForm/>}
      {store.logVisible && <Console/>}
    </AuthDiv>
  )
})
