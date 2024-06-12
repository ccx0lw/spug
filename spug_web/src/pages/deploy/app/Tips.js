/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Tooltip } from 'antd';

const Tips1 = (
  <a
    target="_blank"
    rel="noopener noreferrer"
    href="https://spug.cc/docs/deploy-config#global-env">内置全局变量</a>
)

const Tips2 = (
  <Tooltip title="配置中心应用的配置">
    <span style={{color: '#2563fc'}}>配置中心的配置变量</span>
  </Tooltip>
)

export default (
  <span>可使用 {Tips1} 和 {Tips2}</span>
)