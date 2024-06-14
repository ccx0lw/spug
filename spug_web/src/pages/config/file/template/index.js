/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, Select } from 'antd';
import { SearchForm, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import store from './store';

export default observer(function () {
  return (
    <AuthDiv auth="config.template.file.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>配置中心</Breadcrumb.Item>
        <Breadcrumb.Item>模版文件</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={8} title="模板类型">
          <Select allowClear value={store.f_type} onChange={v => store.f_type = v} placeholder="请选择">
            {store.FileTypes.map(item => (
              <Select.Option value={item} key={item}>{item}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      {store.formVisible && <ComForm/>}
    </AuthDiv>
  );
})
